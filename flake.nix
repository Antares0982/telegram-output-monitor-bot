{
  description = "Forward logs from a RabbitMQ topic exchange to a Telegram chat.";

  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable";

    pyproject-nix = {
      url = "github:pyproject-nix/pyproject.nix";
      inputs.nixpkgs.follows = "nixpkgs";
    };

    uv2nix = {
      url = "github:pyproject-nix/uv2nix";
      inputs.pyproject-nix.follows = "pyproject-nix";
      inputs.nixpkgs.follows = "nixpkgs";
    };

    pyproject-build-systems = {
      url = "github:pyproject-nix/build-system-pkgs";
      inputs.pyproject-nix.follows = "pyproject-nix";
      inputs.uv2nix.follows = "uv2nix";
      inputs.nixpkgs.follows = "nixpkgs";
    };
  };

  outputs =
    {
      self,
      nixpkgs,
      pyproject-nix,
      uv2nix,
      pyproject-build-systems,
    }:
    let
      inherit (nixpkgs) lib;

      forAllSystems = lib.genAttrs [
        "x86_64-linux"
        "aarch64-linux"
        "x86_64-darwin"
        "aarch64-darwin"
      ];

      # Load the uv workspace from the repo root; uv.lock is the single source
      # of truth for dependencies.
      workspace = uv2nix.lib.workspace.loadWorkspace { workspaceRoot = ./.; };

      # Build an overlay of Python packages resolved from uv.lock, preferring
      # prebuilt wheels over sdists.
      overlay = workspace.mkPyprojectOverlay {
        sourcePreference = "wheel";
      };

      # Extra fixups for packages that need them. Empty for now; add here if a
      # dependency's wheel is missing a build system or a native input.
      pyprojectOverrides = _final: _prev: { };

      pythonSets = forAllSystems (
        system:
        let
          pkgs = nixpkgs.legacyPackages.${system};
          python = pkgs.python313;
          baseSet = pkgs.callPackage pyproject-nix.build.packages { inherit python; };
        in
        baseSet.overrideScope (
          lib.composeManyExtensions [
            pyproject-build-systems.overlays.default
            overlay
            pyprojectOverrides
          ]
        )
      );
    in
    {
      packages = forAllSystems (system: {
        default =
          pythonSets.${system}.mkVirtualEnv "telegram-output-monitor-bot-env"
            workspace.deps.default;
      });

      # `nix run` -> runs the `monitor` console script from the built venv.
      apps = forAllSystems (system: {
        default = {
          type = "app";
          program = "${self.packages.${system}.default}/bin/monitor";
        };
      });

      # NixOS module: runs the bot as a systemd service. The user points
      # `services.telegram-output-monitor-bot.environmentFile` at a file that
      # defines ANTARES_MONITOR_MYID and ANTARES_MONITOR_TOKEN.
      nixosModules.default = import ./nix/module.nix self;

      devShells = forAllSystems (
        system:
        let
          pkgs = nixpkgs.legacyPackages.${system};
          python = pkgs.python313;

          # Editable overlay so the workspace package is installed in editable
          # mode (source stays live from the repo tree).
          editableOverlay = workspace.mkEditablePyprojectOverlay {
            root = "$REPO_ROOT";
          };
          editablePythonSet = pythonSets.${system}.overrideScope (
            lib.composeManyExtensions [
              editableOverlay
              (final: prev: {
                telegram-output-monitor-bot = prev.telegram-output-monitor-bot.overrideAttrs (old: {
                  nativeBuildInputs = old.nativeBuildInputs ++ final.resolveBuildSystem { editables = [ ]; };
                });
              })
            ]
          );
          virtualenv = editablePythonSet.mkVirtualEnv "telegram-output-monitor-bot-dev-env" workspace.deps.all;
        in
        {
          # uv2nix-managed editable venv; used by `use flake` / direnv.
          default = pkgs.mkShell {
            packages = [
              virtualenv
              pkgs.uv
            ];
            env = {
              UV_NO_SYNC = "1";
              UV_PYTHON = "${virtualenv}/bin/python";
              UV_PYTHON_DOWNLOADS = "never";
            };
            shellHook = ''
              unset PYTHONPATH
              export REPO_ROOT=$(git rev-parse --show-toplevel)
            '';
          };

          # Native uv workflow: bare interpreter + uv, uv manages its own venv.
          impure = pkgs.mkShell {
            packages = [
              python
              pkgs.uv
            ];
            env = {
              UV_PYTHON = "${python}/bin/python";
              UV_PYTHON_DOWNLOADS = "never";
            };
            shellHook = ''
              unset PYTHONPATH
            '';
          };
        }
      );
    };
}
