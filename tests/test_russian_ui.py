"""Offline localization/layout checks. No console files or SDL device are opened.

Run: python -m unittest discover -s tests -v
Set ANBERNIC_UI_FONT to a copy of the console's default.ttf for exact metrics.
The default DejaVu Sans font is a portable layout proxy, not a firmware font.
"""
import ast
import importlib.util
import json
import os
from pathlib import Path
import re
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[1]
SETTINGS = ROOT / 'Modify_System_Settings/mod_set'
FONT = os.environ.get('ANBERNIC_UI_FONT', 'DejaVuSans.ttf')
SIZES = ((640, 480), (720, 480), (720, 720))
APPS = (
    ('Theme_Manager/themes_ins', ('load_console_menu', 'load_theme_menu', 'load_logo_menu', 'load_help_menu')),
    ('Image_Browser/img_browser', ('handle_browser_input',)),
    ('Bezel_Custom_Manager/bezels_m', ('load_console_menu', 'load_cfg_menu', 'load_help_menu')),
)


def reject_duplicates(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f'Duplicate key: {key}')
        result[key] = value
    return result


def read_locale(directory):
    return json.loads((ROOT / directory / 'lang/ru_RU.json').read_text(encoding='utf-8'),
                      object_pairs_hook=reject_duplicates)


def graphics(directory=SETTINGS):
    spec = importlib.util.spec_from_file_location('settings_graphics_test', directory / 'graphic.py')
    module = importlib.util.module_from_spec(spec)
    with patch.dict(sys.modules, {'main': SimpleNamespace(hw_info=5, hdmi_info='HDMI=0'),
                                 'sdl2': SimpleNamespace()}):
        spec.loader.exec_module(module)
    module.font_file = FONT
    return module


def canvas(module, width, height, scale=1.0):
    # Allocate without __init__, which would open a real SDL window.
    ui = object.__new__(module.UserInterface)
    ui.screen_width, ui.screen_height = width, height
    ui.active_image = Image.new('RGB', (width, height))
    ui.active_draw = ImageDraw.Draw(ui.active_image)
    ui.records = []
    ui.panels = []
    draw_rectangle = ui.draw_rectangle_r

    def panel(position, radius, **kwargs):
        ui.panels.append(position)
        draw_rectangle(position, radius, **kwargs)

    ui.draw_rectangle_r = panel
    real_truetype = ImageFont.truetype

    def font(size):
        return real_truetype(FONT, round(size * scale))

    module.ImageFont = SimpleNamespace(truetype=lambda filename, size: font(size))

    def draw_text(position, text, font=21, color='white', **kwargs):
        face = real_truetype(FONT, round(font * scale))
        bbox = ui.active_draw.textbbox(position, text, font=face, **kwargs)
        ui.records.append((text, bbox, font))
        ui.active_draw.text(position, text, font=face, fill=color, **kwargs)

    ui.draw_text = draw_text
    return ui


def option_pairs(locale):
    aliases = {'menu.1-mode': 'menu.mode', 'menu.a_lock': 'menu.p_lock',
               'menu.sfont': 'menu.font', 'menu.hdmi': 'menu.p_hdmi'}
    for key in locale:
        if not key.startswith('menu.') or key.count('.') != 1:
            continue
        prefix = aliases.get(key, key)
        options = [k for k in locale if re.fullmatch(re.escape(prefix) + r'\.\d+', k)]
        for option in options:
            yield locale[key], locale[option]
    yield locale['menu.0-lang'], 'Русский'
    yield locale['menu.ra_hotkey'], ''
    yield locale['menu.timezone'], 'America/Argentina/ComodRivadavia (UTC-3)'


def footer_items(directory, function, width, height, state='OFF'):
    tree = ast.parse((ROOT / directory / 'app.py').read_text(encoding='utf-8'))
    body = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == function)
    locale = read_locale(directory)
    env = {'button_x': width - 120, 'button_y': height - 30, 'x_size': width,
           'y_size': height, 'translator': SimpleNamespace(translate=lambda key: locale.get(key, key)),
           'an': SimpleNamespace(get_sd_storage=lambda: 1),
           'cf': SimpleNamespace(get_config=lambda key: state)}
    # Read the actual module's button offsets rather than duplicating layout constants.
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id in ('button_x', 'button_y') for t in node.targets):
            for target in node.targets:
                env[target.id] = eval(compile(ast.Expression(node.value), '<layout>', 'eval'),
                                      {'__builtins__': {}}, env)
    items = {}
    for node in ast.walk(body):
        if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
            continue
        if node.func.attr not in ('button_circle', 'button_rectangle'):
            continue
        pos, button, label = [eval(compile(ast.Expression(a), '<caption>', 'eval'),
                                   {'__builtins__': {}}, env) for a in node.args[:3]]
        offset = 65 if node.func.attr == 'button_rectangle' else 30
        end = pos[0] + offset + ImageFont.truetype(FONT, 19).getlength(label)
        index = (pos[0], button)
        # Apply/Delete are mutually exclusive alternatives at the same location.
        if index not in items or items[index][2] < end:
            items[index] = (pos[0], label, end)
    return sorted(items.values())


class LocaleTests(unittest.TestCase):
    def test_all_ten_locales_are_valid(self):
        paths = sorted(ROOT.glob('*/**/lang/ru_RU.json'))
        self.assertEqual(len(paths), 10)
        for path in paths:
            with self.subTest(path=path.relative_to(ROOT)):
                data = json.loads(path.read_text(encoding='utf-8'), object_pairs_hook=reject_duplicates)
                self.assertTrue(data)
                for key, value in data.items():
                    self.assertIsInstance(value, str)
                    self.assertTrue(value.strip(), key)
                    value.format()
                    self.assertNotIn('\ufffd', value)
                    if key != 'menu.lang.help':
                        self.assertIsNone(re.search(r'[\u4e00-\u9fff]', value), key)

    def test_reviewed_app_literal_keys_have_russian_values(self):
        for directory, _ in APPS:
            locale = read_locale(directory)
            tree = ast.parse((ROOT / directory / 'app.py').read_text(encoding='utf-8'))
            for call in ast.walk(tree):
                if (isinstance(call, ast.Call) and isinstance(call.func, ast.Attribute)
                        and call.func.attr == 'translate' and call.args
                        and isinstance(call.args[0], ast.Constant)):
                    with self.subTest(app=directory, key=call.args[0].value):
                        self.assertIn(call.args[0].value, locale)

    def test_bezel_default_is_localized_at_both_call_sites(self):
        source = (ROOT / 'Bezel_Custom_Manager/bezels_m/app.py').read_text(encoding='utf-8')
        locale = read_locale('Bezel_Custom_Manager/bezels_m')
        self.assertEqual(locale.get('default'), 'по умолчанию')
        self.assertEqual(source.count("translator.translate('default')"), 2)
        self.assertNotIn('overlay_name = "default"', source)


class LayoutTests(unittest.TestCase):
    def test_settings_columns_do_not_overlap(self):
        locale = read_locale('Modify_System_Settings/mod_set')
        for width, height in SIZES:
            for scale in (1.0, 1.25):
                module = graphics()
                ui = canvas(module, width, height, scale)
                for left, right in option_pairs(locale):
                    for arrows in (True, False):
                        with self.subTest(size=(width, height), scale=scale, left=left, right=right, arrows=arrows):
                            ui.records.clear()
                            ui.row_list_dual(left, right, (20, 50), width - 40, True, show_arrows=arrows)
                            ltext, lbox, _ = ui.records[-2]
                            rtext, rbox, _ = ui.records[-1]
                            self.assertEqual(ltext, left)
                            self.assertIn(right, rtext)
                            self.assertLessEqual(lbox[2] + 8, rbox[0])
                            self.assertGreaterEqual(lbox[0], 28)
                            self.assertLessEqual(rbox[2], width - 28)
                            for box in (lbox, rbox):
                                self.assertGreaterEqual(box[1], 50)
                                self.assertLessEqual(box[3], 82)

    def test_settings_help_stays_inside_panel(self):
        locale = read_locale('Modify_System_Settings/mod_set')
        texts = {k: v for k, v in locale.items() if k.endswith('.help') or '.opt.' in k}
        for width, height in SIZES:
            for scale in (1.0, 1.25):
                ui = canvas(graphics(), width, height, scale)
                for key, text in texts.items():
                    with self.subTest(size=(width, height), scale=scale, key=key):
                        ui.records.clear()
                        ui.draw_help(text)
                        rendered = ''.join(t for t, _, _ in ui.records)
                        self.assertEqual(''.join(rendered.split()), ''.join(text.split()))
                        for _, box, _ in ui.records:
                            self.assertGreaterEqual(box[0], 25)
                            self.assertLessEqual(box[2], width - 25)
                            self.assertGreaterEqual(box[1], height - 175)
                            self.assertLessEqual(box[3], height - 55)

    def test_tools_help_stays_inside_panel(self):
        directory = 'Modify_System_Tools/mod_tools'
        locale = read_locale(directory)
        for width, height in SIZES:
            for scale in (1.0, 1.25):
                ui = canvas(graphics(ROOT / directory), width, height, scale)
                for key, text in locale.items():
                    if not (key.endswith('.help') or '.opt.' in key):
                        continue
                    with self.subTest(size=(width, height), scale=scale, key=key):
                        ui.records.clear()
                        ui.draw_help(text)
                        self.assertEqual(''.join(''.join(t for t, _, _ in ui.records).split()), ''.join(text.split()))
                        for _, box, _ in ui.records:
                            self.assertGreaterEqual(box[0], 25)
                            self.assertLessEqual(box[2], width - 25)
                            self.assertGreaterEqual(box[1], height - 175)
                            self.assertLessEqual(box[3], height - 55)

    def test_notifications_fit_their_panel(self):
        messages = (
            'Готово: Автоблокировка и крышка SP -> Быстрое выключение',
            'Резервная копия игровых сохранений записана в: /mnt/mmc/anbernic/backup/save.tar.gz',
            'Нет подключения к интернету. Подключитесь к сети и повторите попытку.',
        )
        for directory in (SETTINGS, ROOT / 'Modify_System_Tools/mod_tools'):
            for width, height in SIZES:
                for scale in (1.0, 1.25):
                    ui = canvas(graphics(directory), width, height, scale)
                    for message in messages:
                        with self.subTest(app=directory.name, size=(width, height), scale=scale, message=message):
                            ui.records.clear()
                            ui.draw_log(message)
                            x1, y1, x2, y2 = ui.panels[-1]
                            self.assertGreaterEqual(x1, 10)
                            self.assertGreaterEqual(y1, 10)
                            self.assertLessEqual(x2, width - 10)
                            self.assertLessEqual(y2, height - 10)
                            for _, box, _ in ui.records:
                                self.assertGreaterEqual(box[0], x1 + 5)
                                self.assertGreaterEqual(box[1], y1 + 5)
                                self.assertLessEqual(box[2], x2 - 5)
                                self.assertLessEqual(box[3], y2 - 5)

    def test_theme_help_pages_stay_inside_panel(self):
        directory = 'Theme_Manager/themes_ins'
        locale = read_locale(directory)
        full = '\n'.join(locale[k] for k in ('message_02-1', 'message_02-2', 'message_02-3'))
        short = {k: v for k, v in locale.items() if k.endswith('_help') or k.startswith('help_')}
        for width, height in SIZES:
            for scale in (1.0, 1.25):
                ui = canvas(graphics(ROOT / directory), width, height, scale)
                for key, text in [('full', full), *short.items()]:
                    with self.subTest(size=(width, height), scale=scale, key=key):
                        ui.records.clear()
                        if key == 'full':
                            ui.draw_help2(text, font=19)
                            top, bottom = 45, height - 45
                        else:
                            ui.draw_help(text)
                            top, bottom = height - 105, height - 40
                        self.assertEqual(''.join(''.join(t for t, _, _ in ui.records).split()), ''.join(text.split()))
                        for _, box, _ in ui.records:
                            self.assertGreaterEqual(box[0], 25)
                            self.assertLessEqual(box[2], width - 25)
                            self.assertGreaterEqual(box[1], top)
                            self.assertLessEqual(box[3], bottom)

    def test_bezel_help_fits_its_fixed_page(self):
        locale = read_locale('Bezel_Custom_Manager/bezels_m')
        text = '\n'.join(locale[k] for k in ('message_02-1', 'message_02-2', 'message_02-3'))
        for width, height in SIZES:
            for scale in (1.0, 1.25):
                with self.subTest(size=(width, height), scale=scale):
                    draw = ImageDraw.Draw(Image.new('RGB', (width, height)))
                    box = draw.multiline_textbbox((width / 2, height / 2), text,
                                                 font=ImageFont.truetype(FONT, round(21 * scale)), anchor='mm')
                    self.assertGreaterEqual(box[0], 25)
                    self.assertLessEqual(box[2], width - 25)
                    self.assertGreaterEqual(box[1], 45)
                    self.assertLessEqual(box[3], height - 45)

    def test_footer_controls_do_not_overlap(self):
        for width, height in SIZES:
            for directory, functions in APPS:
                for function in functions:
                    for state in ('ON', 'OFF'):
                        with self.subTest(size=(width, height), app=directory, page=function, state=state):
                            items = footer_items(directory, function, width, height, state)
                            for first, second in zip(items, items[1:]):
                                self.assertLessEqual(first[2] + 6, second[0], f'{first} overlaps {second}')
                            self.assertLessEqual(items[-1][2], width - 6)


if __name__ == '__main__':
    unittest.main()
