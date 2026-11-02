from collections import OrderedDict
from pathlib import Path
import os
import shutil
import tempfile

config_file = '/mnt/mod/ctrl/configs/system.cfg'

file_path = Path(config_file)
file_path.parent.mkdir(parents=True, exist_ok=True)
file_path.touch()

def read_config(filename):
    config = OrderedDict()
    try:
        with open(filename, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith('#'):
                    continue
                if '=' in line:
                    key, value = line.split('=', 1)
                    config[key.strip()] = value.strip()
    except FileNotFoundError:
        print("file does not exist")
    return config

def write_config(filename, config):
    # Follow existing symlinks rather than replacing the link itself. Keep the
    # temporary file on the target filesystem so replacement is atomic.
    target = os.path.realpath(filename)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8',
                                         dir=os.path.dirname(target),
                                         prefix='.system-', delete=False) as f:
            temporary = f.name
            for key, value in config.items():
                f.write(f"{key}={value}\n")
            f.flush()
            if os.path.exists(target):
                previous = os.stat(target)
                current = os.fstat(f.fileno())
                if (current.st_uid, current.st_gid) != (previous.st_uid, previous.st_gid):
                    os.fchown(f.fileno(), previous.st_uid, previous.st_gid)
                shutil.copystat(target, temporary)
            else:
                os.fchmod(f.fileno(), 0o644)
            os.fsync(f.fileno())
        os.replace(temporary, target)
        temporary = None
    finally:
        if temporary is not None:
            os.unlink(temporary)

def update_config(config, new_entries):
    for key, value in new_entries.items():
        if key in config:
            del config[key]
        config[key] = value

def remove_config(config, key_to_delete):
    if key_to_delete in config:
        del config[key_to_delete]

def get_value(config, keys):
    for key, value in config.items():
        print(key, value)
        if key == keys:
            return value
    return None

def set_config(keys, value):
    config = read_config(config_file)
    new_settings = {keys: value}
    update_config(config, new_settings)
    write_config(config_file, config)

def del_config(keys):
    config = read_config(config_file)
    remove_config(config, keys)
    write_config(config_file, config)

def get_config(keys):
    try:
        config = read_config(config_file)
        values = get_value(config, keys)
    except (OSError, UnicodeError) as error:
        print(f"[ERROR]Cannot read setting {keys}: {error}")
        return "UNKNOWN"
    return {"0": "OFF", "1": "ON", "2": "AUTO"}.get(values, "UNKNOWN")


def switch_config(keys, max):
    config = read_config(config_file)
    cur_value = get_value(config, keys)
    if cur_value is None:
        raise ValueError(f"Missing setting: {keys}")
    cur_value = int(cur_value)
    if max <= 0 or not 0 <= cur_value < max:
        raise ValueError(f"Invalid value for setting {keys}: {cur_value}")
    set_config(keys, (cur_value + 1) % max)
