# PlatformIO hook: keep the pad's saved config across `pio run -t uploadfs`.
#
# uploadfs replaces the whole filesystem, including /macros.json. Before the
# image is built, this reads the current config off the pad over USB, keeps a
# timestamped gzipped copy in backups/ (newest 5 kept), and builds the image with that config in place
# of data/macros.json. Firmware-only uploads (`-t upload`) never touch the
# filesystem, so they need none of this.
#
#   pio run -t backup                         just save a copy in backups/
#   KABUTO_RESTORE=backups/x.json.gz pio run -t uploadfs   flash that file instead
#   KABUTO_SKIP_BACKUP=1 pio run -t uploadfs  flash data/macros.json (wipes yours)
Import("env")
import os, shutil, sys

sys.path.insert(0, os.path.join(env.subst("$PROJECT_DIR"), "tools"))
import flash_backup

BACKUP_DIR = os.path.join(env.subst("$PROJECT_DIR"), "backups")

def ensure_littlefs():
    try:
        import littlefs  # noqa: F401
    except ImportError:
        env.Execute('"$PYTHONEXE" -m pip install "littlefs-python>=0.12"')

def read_pad_config():
    ensure_littlefs()
    esptool_dir = env.PioPlatform().get_package_dir("tool-esptoolpy")
    esptool = [env.subst("$PYTHONEXE"), os.path.join(esptool_dir, "esptool.py")] if esptool_dir \
        else [env.subst("$PYTHONEXE"), "-m", "esptool"]
    baud = env.subst("$UPLOAD_SPEED") or env.BoardConfig().get("upload.speed", 460800)
    return flash_backup.fetch_config(esptool, chip=env.BoardConfig().get("build.mcu", "esp32s3"),
                                     port=env.subst("$UPLOAD_PORT") or None, baud=baud)

def backup_action(*_):
    config = read_pad_config()
    if config is None:
        print("No saved config on the pad yet - nothing to back up.")
    else:
        print("Kabuto config saved to", flash_backup.save_backup(config, BACKUP_DIR))

def stage_data_dir(config):
    """Build the filesystem image from a copy of data/ holding this config."""
    staging = os.path.join(env.subst("$BUILD_DIR"), "fs-data")
    shutil.rmtree(staging, ignore_errors=True)
    shutil.copytree(env.subst("$PROJECT_DATA_DIR"), staging)
    with open(os.path.join(staging, flash_backup.CONFIG_NAME), "wb") as f:
        f.write(config)
    env.Replace(PROJECT_DATA_DIR=staging)

env.AddCustomTarget("backup", None, backup_action, title="Back up config",
                    description="Copy macros.json off the pad over USB into backups/")

if "uploadfs" in COMMAND_LINE_TARGETS and not os.environ.get("KABUTO_SKIP_BACKUP"):
    restore = os.environ.get("KABUTO_RESTORE")
    if restore:
        config = flash_backup.load_backup(restore)   # refuses a broken file
        print("Kabuto: flashing config from", restore)
        stage_data_dir(config)
    else:
        try:
            config = read_pad_config()
        except Exception as e:
            print("\nKabuto: couldn't read the config saved on the pad (%s).\n"
                  "uploadfs was stopped so your patterns aren't overwritten. Check the USB\n"
                  "cable/port, or run with KABUTO_SKIP_BACKUP=1 to flash data/macros.json.\n" % e)
            env.Exit(1)
        if config is None:
            print("Kabuto: no saved config on the pad - flashing data/macros.json.")
        else:
            try:
                print("Kabuto: config backed up to", flash_backup.save_backup(config, BACKUP_DIR))
            except ValueError:
                print("\nKabuto: the config on the pad isn't valid JSON, so it can't be kept.\n"
                      "Run with KABUTO_SKIP_BACKUP=1 to flash data/macros.json instead.\n")
                env.Exit(1)
            stage_data_dir(config)
