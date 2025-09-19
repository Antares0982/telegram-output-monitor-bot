{
  pkgs,
  stdenvNoCC,
  python3,
  callPackage,
  ...
}:
let
  # import required python packages
  requiredPythonPackages = callPackage ./py_requirements.nix { };
  # create python environment
  pyenv = python3.withPackages requiredPythonPackages;
in
stdenvNoCC.mkDerivation rec {
  name = "telegram-output-monitor-bot";
  src = builtins.path {
    inherit name;
    path = ./.;
  };
  phases = [
    "unpackPhase"
    "installPhase"
  ];
  installPhase = ''
    mkdir -p $out/bin
    cp $src/monitor.py $out/bin
    shebang="#!${pyenv}/bin/python"
    sed -i "1s|.*|$shebang|" "$out/bin/monitor.py"
    chmod +x "$out/bin/monitor.py"
  '';
}
