self:
{
  config,
  lib,
  pkgs,
  ...
}:
let
  cfg = config.services.telegram-output-monitor-bot;
in
{
  options.services.telegram-output-monitor-bot = {
    enable = lib.mkEnableOption "the Telegram output monitor bot systemd service";

    package = lib.mkOption {
      type = lib.types.package;
      default = self.packages.${pkgs.stdenv.hostPlatform.system}.default;
      defaultText = lib.literalExpression "telegram-output-monitor-bot.packages.\${system}.default";
      description = "The telegram-output-monitor-bot package to run.";
    };

    environmentFile = lib.mkOption {
      type = with lib.types; either path (listOf path);
      example = "/run/secrets/telegram-output-monitor-bot.env";
      description = ''
        Path (or list of paths) to an environment file loaded by systemd via
        `EnvironmentFile=`. It must define the two variables the bot requires:

        ```
        ANTARES_MONITOR_MYID=123456789
        ANTARES_MONITOR_TOKEN=your-telegram-bot-token
        ```

        Keep this file out of the Nix store (e.g. managed by agenix/sops or
        deployed out of band) so the token stays secret.
      '';
    };
  };

  config = lib.mkIf cfg.enable {
    systemd.services.telegram-output-monitor-bot = {
      description = "Forward logs from a RabbitMQ topic exchange to a Telegram chat";
      wantedBy = [ "multi-user.target" ];
      after = [ "network-online.target" ];
      wants = [ "network-online.target" ];

      serviceConfig = {
        ExecStart = "${lib.getExe' cfg.package "monitor"}";
        EnvironmentFile = cfg.environmentFile;
        Restart = "on-failure";
        RestartSec = 5;

        # Run as an unprivileged, isolated user.
        DynamicUser = true;

        # Hardening: the bot only needs network access, no filesystem writes.
        NoNewPrivileges = true;
        ProtectSystem = "strict";
        ProtectHome = true;
        PrivateTmp = true;
        PrivateDevices = true;
        ProtectKernelTunables = true;
        ProtectKernelModules = true;
        ProtectControlGroups = true;
        RestrictAddressFamilies = [
          "AF_INET"
          "AF_INET6"
          "AF_UNIX"
        ];
        RestrictNamespaces = true;
        LockPersonality = true;
        MemoryDenyWriteExecute = true;
        SystemCallArchitectures = "native";
      };
    };
  };
}
