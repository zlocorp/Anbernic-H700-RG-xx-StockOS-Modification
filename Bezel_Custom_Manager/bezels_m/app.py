from pathlib import Path
from PIL import Image
from main import hw_info, system_lang
from graphic import screen_resolutions, UserInterface
from language import Translator
import os
import config as cf
import input
import sys
import time
from anbernic import Anbernic
from bezels import Bezels

ver="v1.2"
translator = Translator(system_lang)
gr = UserInterface()
cfg_is_ok = 0
previewed_bezel_file = None
selected_position = 0
roms_selected_position = 0
selected_system = ""
current_window = "console"
an = Anbernic()
bezels = Bezels()
skip_input_check = True

x_size, y_size, max_elem = screen_resolutions.get(hw_info, (640, 480, 11))

button_x = x_size - 120
button_y = y_size - 30
ratio = y_size / x_size


def get_overlay_image(bezel_file, system_path, check_image=False):
    """Return an existing overlay image, or None for an unusable config."""
    try:
        with open(bezel_file, 'r') as file_object:
            for line in file_object:
                key, separator, value = line.partition('=')
                if not separator or key.strip() != 'overlay0_overlay':
                    continue
                value = value.strip()
                if value.startswith(("'", '"')):
                    if len(value) < 2 or value[-1] != value[0]:
                        return None
                    value = value[1:-1]
                if not value:
                    return None
                image_path = Path(system_path) / value
                if not image_path.is_file():
                    return None
                if check_image:
                    with Image.open(image_path) as image:
                        image.load()
                return str(image_path)
    except (OSError, UnicodeError, ValueError, Image.DecompressionBombError):
        return None
    return None


def get_current_overlay_name(cfg_file):
    try:
        with open(cfg_file, 'r') as file_object:
            value = file_object.readline().strip()
        if len(value) >= 2 and value[0] in ("'", '"') and value[-1] == value[0]:
            value = value[1:-1]
        path = Path(value)
        if path.suffix.lower() == '.cfg' and path.stem:
            return path.stem
    except FileNotFoundError:
        return translator.translate('default')
    except (OSError, UnicodeError, ValueError):
        pass
    return translator.translate('Unknown')


def start():
    print("[INFO]Starting Custom Bezel Manager...")
    gr.draw_log(
        f"{translator.translate('Welcome')}", fill=gr.colorBlue, outline=gr.colorBlueD1
    )
    gr.draw_paint()
    time.sleep(2)
    load_console_menu()


def update() -> None:
    global current_window, selected_position, skip_input_check

    if skip_input_check:
        input.reset_input()
        skip_input_check = False
    else:
        input.check()

    if input.key("SELECT"):
        gr.draw_end()
        print("[INFO]Exiting Custom Bezel Manager...")
        sys.exit()

    if current_window == "console":
        load_console_menu()
    elif current_window == "cfg":
        load_cfg_menu()
    elif current_window == "help":
        load_help_menu()
    else:
        load_console_menu()


def load_console_menu() -> None:
    global selected_position, selected_system, current_window, skip_input_check

    available_systems = bezels.get_available_systems(an.get_sd_storage_path())

    if available_systems:
        if input.key("DY"):
            selected_position = (selected_position + input.value) % len(available_systems)
        elif input.key("L1"):
            if selected_position > 0:
                selected_position = max(0, selected_position - max_elem)
        elif input.key("R1"):
            if selected_position < len(available_systems) - 1:
                selected_position = min(
                    len(available_systems) - 1, selected_position + max_elem
                )
        elif input.key("L2"):
            if selected_position > 0:
                selected_position = max(0, selected_position - 100)
        elif input.key("R2"):
            if selected_position < len(available_systems) - 1:
                selected_position = min(
                    len(available_systems) - 1, selected_position + 100
                )
        elif input.key("A"):
            selected_system = available_systems[selected_position]
            current_window = "cfg"
            gr.draw_log(
                f"{translator.translate('Checking bezel config file...')}", fill=gr.colorBlue, outline=gr.colorBlueD1
            )
            gr.draw_paint()
            skip_input_check = True
            return
        elif input.key("Y"):
            current_window = "help"
            skip_input_check = True
            return

    gr.draw_clear()

    gr.draw_rectangle_r([10, 40, x_size - 10, y_size - 40], 15, fill=gr.colorGrayD2, outline=None)
    gr.draw_text((x_size / 2, 20), f"{translator.translate('Bezel Custom Manager')} {ver}", font=23, anchor="mm")

    if len(available_systems) > 1:
        start_idx = int(selected_position / max_elem) * max_elem
        end_idx = start_idx + max_elem
        for i, system in enumerate(available_systems[start_idx:end_idx]):
            gr.row_list(
                system, (20, 50 + (i * 35)), x_size - 40, i == (selected_position % max_elem)
            )
        gr.button_circle((20, button_y), "A", f"{translator.translate('Select')}")
    else:
        gr.draw_text(
            (x_size / 2, y_size / 2), f"{translator.translate('No config file found in SD')} {an.get_sd_storage()}", anchor="mm"
        )

    gr.button_circle((button_x - 110, button_y), "Y", f"{translator.translate('Help')}")
    gr.button_rectangle((button_x, button_y), "SEL", f"{translator.translate('Exit')}")

    gr.draw_paint()


def load_cfg_menu() -> None:
    global \
        selected_position, \
        current_window, \
        roms_selected_position, \
        skip_input_check, \
        selected_system, \
        cfg_is_ok, \
        previewed_bezel_file

    exit_menu = False
    roms_list = bezels.get_roms(an.get_sd_storage_path(), selected_system)
    previous_position = roms_selected_position
    roms_selected_position = max(0, min(roms_selected_position, len(roms_list) - 1))
    if roms_selected_position != previous_position:
        # Do not apply a cached Apply/Delete action to a different surviving item.
        cfg_is_ok = 0
    system_path = Path(an.get_sd_storage_path()) / selected_system
    cfg_path = Path(an.get_bezels_cfg_path())
    cfg_file = f"{cfg_path}/{selected_system}.cfg"

    if len(roms_list) < 1:
        current_window = "console"
        selected_system = ""
        gr.draw_log(
            f"{translator.translate('No config file found...')}", fill=gr.colorBlue, outline=gr.colorBlueD1
        )
        gr.draw_paint()
        time.sleep(2)
        gr.draw_clear()
        skip_input_check = True
        return

    if input.key("B"):
        exit_menu = True
    elif input.key("X"):
        cfg_file = f"{cfg_path}/{selected_system}.cfg"
        gr.draw_log(f"{translator.translate('Resetting...')}", fill=gr.colorBlue, outline=gr.colorBlueD1)
        gr.draw_paint()
        try:
            cf.set_config("global.bezel", 1)
        except (OSError, UnicodeError) as error:
            print(f"[ERROR]Cannot enable bezels for reset: {error}")
            gr.draw_log(translator.translate('Operation failed. See log for details.'),
                        fill=gr.colorBlue, outline=gr.colorBlueD1)
        else:
            try:
                try:
                    os.unlink(cfg_file)
                except FileNotFoundError:
                    pass
            except OSError as error:
                print(f"[ERROR]Bezels enabled, but selection reset failed: {error}")
                gr.draw_log(translator.translate('Bezels were enabled, but the selected bezel could not be reset.'),
                            fill=gr.colorBlue, outline=gr.colorBlueD1)
            else:
                gr.draw_log(
                    f"{translator.translate('Reset bezel for')} {selected_system} {translator.translate('to')} {translator.translate('default')}",
                    fill=gr.colorBlue, outline=gr.colorBlueD1
                )
        gr.draw_paint()
        time.sleep(3)
        exit_menu = True
    elif input.key("DY"):
        roms_selected_position = (roms_selected_position + input.value) % len(roms_list)
    elif input.key("L1"):
        if roms_selected_position > 0:
            roms_selected_position = max(0, roms_selected_position - max_elem)
    elif input.key("R1"):
        if roms_selected_position < len(roms_list) - 1:
            roms_selected_position = min(
                len(roms_list) - 1, roms_selected_position + max_elem
            )
    elif input.key("L2"):
        if roms_selected_position > 0:
            roms_selected_position = max(0, roms_selected_position - 100)
    elif input.key("R2"):
        if roms_selected_position < len(roms_list) - 1:
            roms_selected_position = min(
                len(roms_list) - 1, roms_selected_position + 100
            )

    elif input.key("A") and previewed_bezel_file == str(system_path / roms_list[roms_selected_position].filename):
        if cfg_is_ok == 1:
            rom = roms_list[roms_selected_position]
            bezel_file = f"{system_path}/{rom.filename}"
            img_file = get_overlay_image(bezel_file, system_path, check_image=True)
            if img_file is not None:
                cfg_file = f"{cfg_path}/{selected_system}.cfg"
                gr.draw_log(f"{translator.translate('Setting...')}", fill=gr.colorBlue, outline=gr.colorBlueD1)
                gr.draw_paint()
                try:
                    cfg_path.mkdir(parents=True, exist_ok=True)
                    cf.write_text(cfg_file, f"{bezel_file}\n")
                except (OSError, UnicodeError) as error:
                    print(f"[ERROR]Cannot save bezel selection: {error}")
                    gr.draw_log(translator.translate('Operation failed. See log for details.'),
                                fill=gr.colorBlue, outline=gr.colorBlueD1)
                else:
                    try:
                        cf.set_config("global.bezel", 1)
                    except (OSError, UnicodeError) as error:
                        print(f"[ERROR]Selection saved, but enabling bezels failed: {error}")
                        gr.draw_log(translator.translate('Bezel selection was saved, but enabling bezels failed.'),
                                    fill=gr.colorBlue, outline=gr.colorBlueD1)
                    else:
                        gr.draw_log(
                            f"{selected_system} {translator.translate('bezel set to')} {rom.name}",
                            fill=gr.colorBlue, outline=gr.colorBlueD1
                        )
                gr.draw_paint()
                time.sleep(3)
            else:
                cfg_is_ok = 2
                gr.draw_log(
                    f"{translator.translate('The .cfg file has an issue and cannot be used!')}", fill=gr.colorBlue, outline=gr.colorBlueD1
                )
                gr.draw_paint()
                time.sleep(2)
            exit_menu = True
        elif cfg_is_ok == 2:
            rom_to_delete = roms_list[roms_selected_position]
            bezel_file = f"{system_path}/{rom_to_delete.filename}"
            if get_overlay_image(bezel_file, system_path, check_image=True) is not None:
                # The file or its image may have been repaired since the preview.
                cfg_is_ok = 1
            else:
                try:
                    os.remove(bezel_file)
                except FileNotFoundError:
                    pass
                except OSError as error:
                    print(f"[ERROR]Cannot delete bezel config {bezel_file}: {error}")
                    gr.draw_log(translator.translate('Operation failed. See log for details.'),
                                fill=gr.colorBlue, outline=gr.colorBlueD1)
                    gr.draw_paint()
                    time.sleep(2)
                    skip_input_check = True
                    return
                roms_list.pop(roms_selected_position)

                if not roms_list:
                    current_window = "console"
                    selected_system = ""
                    gr.draw_clear()
                    roms_selected_position = 0
                    skip_input_check = True
                    return

                if roms_selected_position >= len(roms_list):
                    roms_selected_position = len(roms_list) - 1

    if exit_menu:
        current_window = "console"
        selected_system = ""
        gr.draw_clear()
        roms_selected_position = 0
        skip_input_check = True
        return

    overlay_name = get_current_overlay_name(cfg_file)
    gr.draw_clear()

    gr.draw_rectangle_r([10, 40, x_size - 10, y_size - 40], 15, fill=gr.colorGray, outline=None)
    gr.draw_text(
        (x_size / 2, 20),
        f"{selected_system} - {translator.translate('bezels')}: {len(roms_list)} | {translator.translate('Current Settings')}: {overlay_name}",
        font=21,
        anchor="mm",
    )

    start_idx = int(roms_selected_position / max_elem) * max_elem
    end_idx = start_idx + max_elem
    for i, rom in enumerate(roms_list[start_idx:end_idx]):
        gr.row_list(
            rom.name[:48] + "..." if len(rom.name) > 50 else rom.name,
            (20, 50 + (i * 35)),
            x_size -40,
            i == (roms_selected_position % max_elem),
        )

    rom = roms_list[roms_selected_position]
    bezel_file = f"{system_path}/{rom.filename}"
    img_file = get_overlay_image(bezel_file, system_path)
    previewed_bezel_file = bezel_file
    cfg_is_ok = 2
    if img_file is not None:
        try:
            gr.display_image(img_file, target_x = int(x_size / 2 + 10), target_y = int(y_size / 4), target_width = int(x_size / 2 - 30), target_height = int((x_size / 2 - 30) * ratio))
        except (OSError, ValueError, Image.DecompressionBombError) as error:
            print(f"[ERROR]Cannot preview bezel image {img_file}: {error}")
        else:
            cfg_is_ok = 1
    if cfg_is_ok == 2:
        gr.draw_log(
            f"{translator.translate('The .cfg file has an issue and cannot be used!')}", fill=gr.colorBlue, outline=gr.colorBlueD1
        )

    if cfg_is_ok == 1:
        gr.button_circle((20, button_y), "A", f"{translator.translate('Apply')}")
    elif cfg_is_ok == 2:
        gr.button_circle((20, button_y), "A", f"{translator.translate('Delete')}")
    gr.button_circle((160, button_y), "B", f"{translator.translate('Back')}")
    gr.button_circle((280, button_y), "X", f"{translator.translate('Reset')}")
    gr.button_rectangle((button_x, button_y), "SEL", f"{translator.translate('Exit')}")

    gr.draw_paint()


def load_help_menu() -> None:
    global current_window, skip_input_check

    if input.key("B"):
        current_window = "console"
        skip_input_check = True
        return

    gr.draw_clear()

    gr.draw_rectangle_r([10, 40, x_size - 10, y_size - 40], 15, fill=gr.colorGrayL1, outline=None)
    gr.draw_text((x_size / 2, 20), f"{translator.translate('-Help-')}", anchor="mm")

    gr.draw_text(
        (x_size / 2, y_size / 2), f"{translator.translate('message_02-1')}\n{translator.translate('message_02-2')}\n{translator.translate('message_02-3')}", anchor="mm"
    )

    gr.button_circle((20, button_y), "B", f"{translator.translate('Back')}")
    gr.button_rectangle((button_x, button_y), "SEL", f"{translator.translate('Exit')}")

    gr.draw_paint()
