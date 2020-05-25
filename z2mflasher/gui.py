# This GUI is a fork of the brilliant https://github.com/marcelstoer/nodemcu-pyflasher
import re
import sys
import threading

import wx
import wx.adv
from wx.lib.embeddedimage import PyEmbeddedImage
import wx.lib.inspection
import wx.lib.mixins.inspection

from z2mflasher.helpers import list_serial_ports


COLOR_RE = re.compile(r'(?:\033)(?:\[(.*?)[@-~]|\].*?(?:\007|\033\\))')
COLORS = {
    'black': wx.BLACK,
    'red': wx.RED,
    'green': wx.GREEN,
    'yellow': wx.YELLOW,
    'blue': wx.BLUE,
    'magenta': wx.Colour(255, 0, 255),
    'cyan': wx.CYAN,
    'white': wx.WHITE,
}
FORE_COLORS = {**COLORS, None: wx.WHITE}
BACK_COLORS = {**COLORS, None: wx.BLACK}
FLASH_DELAY_S = 5

FILESYSTEM_OFFSET = '1048576' #0x100000

# See discussion at http://stackoverflow.com/q/41101897/131929
class RedirectText:
    def __init__(self, text_ctrl):
        self._out = text_ctrl
        self._i = 0
        self._line = ''
        self._bold = False
        self._italic = False
        self._underline = False
        self._foreground = None
        self._background = None
        self._secret = False

    def _add_content(self, value):
        attr = wx.TextAttr()
        if self._bold:
            attr.SetFontWeight(wx.FONTWEIGHT_BOLD)
        attr.SetTextColour(FORE_COLORS[self._foreground])
        attr.SetBackgroundColour(BACK_COLORS[self._background])
        wx.CallAfter(self._out.SetDefaultStyle, attr)
        wx.CallAfter(self._out.AppendText, value)

    def _write_line(self):
        pos = 0
        while True:
            match = COLOR_RE.search(self._line, pos)
            if match is None:
                break

            j = match.start()
            self._add_content(self._line[pos:j])
            pos = match.end()

            for code in match.group(1).split(';'):
                code = int(code)
                if code == 0:
                    self._bold = False
                    self._italic = False
                    self._underline = False
                    self._foreground = None
                    self._background = None
                    self._secret = False
                elif code == 1:
                    self._bold = True
                elif code == 3:
                    self._italic = True
                elif code == 4:
                    self._underline = True
                elif code == 5:
                    self._secret = True
                elif code == 6:
                    self._secret = False
                elif code == 22:
                    self._bold = False
                elif code == 23:
                    self._italic = False
                elif code == 24:
                    self._underline = False
                elif code == 30:
                    self._foreground = 'black'
                elif code == 31:
                    self._foreground = 'red'
                elif code == 32:
                    self._foreground = 'green'
                elif code == 33:
                    self._foreground = 'yellow'
                elif code == 34:
                    self._foreground = 'blue'
                elif code == 35:
                    self._foreground = 'magenta'
                elif code == 36:
                    self._foreground = 'cyan'
                elif code == 37:
                    self._foreground = 'white'
                elif code == 39:
                    self._foreground = None
                elif code == 40:
                    self._background = 'black'
                elif code == 41:
                    self._background = 'red'
                elif code == 42:
                    self._background = 'green'
                elif code == 43:
                    self._background = 'yellow'
                elif code == 44:
                    self._background = 'blue'
                elif code == 45:
                    self._background = 'magenta'
                elif code == 46:
                    self._background = 'cyan'
                elif code == 47:
                    self._background = 'white'
                elif code == 49:
                    self._background = None

        self._add_content(self._line[pos:])

    def write(self, string):
        for s in string:
            if s == '\r':
                current_value = self._out.GetValue()
                last_newline = current_value.rfind("\n")
                wx.CallAfter(self._out.Remove, last_newline + 1, len(current_value))
                self._line += '\n'
                self._write_line()
                self._line = ''
                continue
            self._line += s
            if s == '\n':
                self._write_line()
                self._line = ''
                continue

    def flush(self):
        pass


class FlashBaseThread(threading.Thread):
    def __init__(self, port):
        threading.Thread.__init__(self)
        self.daemon = True
        self._port = port

    def flash_esp(self, firmware_name, offset=0, erase=False):
        try:
            from z2mflasher.__main__ import run_esphomeflasher
            argv = ['z2mflasher',
                '--esp8266',
                '--port', self._port,
                '--binary', firmware_name]
            if offset != 0:
                argv.append('--offset')
                argv.append(offset)
            if not erase:
                argv.append('--no-erase')
            run_esphomeflasher(argv)
            return
        except Exception as e:
            print("Unexpected error: {}".format(e))
            raise


class FlashingESPThread(FlashBaseThread):
    def __init__(self, port, firmware, offset=0, erase=False):
        FlashBaseThread.__init__(self, port)
        self._esp_firmware = firmware
        self._erase_firmware = erase
        self._offset = offset

    def run(self):
        self.flash_esp(self._esp_firmware, self._offset, self._erase_firmware)


class FlashAllThread(FlashBaseThread):
    def __init__(self, port, esp, fs, erase=False):
        FlashBaseThread.__init__(self, port)
        self._esp_firmware = esp
        self._esp_fs = fs
        self._erase_firmware = erase

    def run(self):
        import time

        print("Flash File system to ESP first.")
        self.flash_esp(self._esp_fs, FILESYSTEM_OFFSET, self._erase_firmware)
        print("Please press reset button. Wait %d seconds." % FLASH_DELAY_S)
        for s in range(FLASH_DELAY_S):
            print("%d ..." % s)
            time.sleep(1)
        print("Flash ESP firmware to module.")
        self.flash_esp(self._esp_firmware)
        print("Flash Done.")


class MainFrame(wx.Frame):
    def __init__(self, parent, title):
        wx.Frame.__init__(self, parent, -1, title, size=(500, 500),
                          style=wx.DEFAULT_FRAME_STYLE | wx.NO_FULL_REPAINT_ON_RESIZE)

        self._esp_firmware = None
        self._esp_fs = None
        self._port = None
        self._erase = False

        self._init_ui()

        self._stdout = sys.stdout
        self._stderr = sys.stderr
        self._redirect = RedirectText(self.console_ctrl)
        sys.stdout = self._redirect
        sys.stderr = self._redirect

        self.SetMinSize((500, 380))
        self.Centre(wx.BOTH)
        self.Show(True)

    def _init_ui(self):
        def on_reload(event):
            self.choice.SetItems(self._get_serial_ports())

        def on_esp_clicked(event):
            self.console_ctrl.SetValue("")
            worker = FlashingESPThread(self._port, self._esp_firmware, self._erase)
            worker.start()

        def on_esp_fs_clicked(event):
            self.console_ctrl.SetValue("")
            worker = FlashingESPThread(self._port, self._esp_fs, FILESYSTEM_OFFSET, self._erase)
            worker.start()

        def on_flash_all_clicked(event):
            self.console_ctrl.SetValue("")
            worker = FlashAllThread(self._port, self._esp_firmware, self._esp_fs, self._erase)
            worker.start()
        
        def on_erase_clicked(event):
            cb = event.GetEventObject() 
            self._erase = cb.GetValue()

        def on_select_port(event):
            choice = event.GetEventObject()
            self._port = choice.GetString(choice.GetSelection())

        def on_pick_esp_file(event):
            self._esp_firmware = event.GetPath().replace("'", "")

        def on_pick_esp_fs_file(event):
            self._esp_fs = event.GetPath().replace("'", "")

        panel = wx.Panel(self)

        hbox = wx.BoxSizer(wx.HORIZONTAL)

        fgs = wx.FlexGridSizer(6, 2, 0, 0)

        self.choice = wx.Choice(panel, choices=self._get_serial_ports())
        self.choice.Bind(wx.EVT_CHOICE, on_select_port)
        bmp = Reload.GetBitmap()
        reload_button = wx.BitmapButton(panel, id=wx.ID_ANY, bitmap=bmp,
                                        size=(bmp.GetWidth() + 7, bmp.GetHeight() + 7))
        reload_button.Bind(wx.EVT_BUTTON, on_reload)
        reload_button.SetToolTip("Reload serial device list")

        esp_file_picker = wx.FilePickerCtrl(panel, style=wx.FLP_USE_TEXTCTRL)
        esp_file_picker.Bind(wx.EVT_FILEPICKER_CHANGED, on_pick_esp_file)

        esp_fs_file_picker = wx.FilePickerCtrl(panel, style=wx.FLP_USE_TEXTCTRL)
        esp_fs_file_picker.Bind(wx.EVT_FILEPICKER_CHANGED, on_pick_esp_fs_file)

        serial_boxsizer = wx.BoxSizer(wx.HORIZONTAL)
        serial_boxsizer.Add(self.choice, 1, wx.EXPAND)
        serial_boxsizer.AddStretchSpacer(0)
        serial_boxsizer.Add(reload_button, 0, wx.ALIGN_RIGHT, 20)

        esp_button = wx.Button(panel, -1, "ESP")
        esp_button.Bind(wx.EVT_BUTTON, on_esp_clicked)

        esp_fs_button = wx.Button(panel, -1, "FileSystem")
        esp_fs_button.Bind(wx.EVT_BUTTON, on_esp_fs_clicked)

        flash_all_button = wx.Button(panel, -1, "All")
        flash_all_button.Bind(wx.EVT_BUTTON, on_flash_all_clicked)

        erase_checkbox = wx.CheckBox(panel, label = 'Erase ESP') 
        erase_checkbox.Bind(wx.EVT_CHECKBOX, on_erase_clicked)

        flash_boxsizer = wx.BoxSizer(wx.HORIZONTAL)
        flash_boxsizer.Add(esp_button, 0, wx.ALIGN_CENTER)
        flash_boxsizer.AddStretchSpacer(0)
        flash_boxsizer.Add(esp_fs_button, 0, wx.ALIGN_CENTER)
        flash_boxsizer.AddStretchSpacer(0)
        flash_boxsizer.Add(flash_all_button, 0, wx.ALIGN_CENTER)
        flash_boxsizer.AddStretchSpacer(0)
        flash_boxsizer.Add(erase_checkbox, 0, wx.ALIGN_CENTER)

        self.console_ctrl = wx.TextCtrl(panel, style=wx.TE_MULTILINE | wx.TE_READONLY | wx.HSCROLL)
        self.console_ctrl.SetFont(wx.Font((0, 13), wx.FONTFAMILY_TELETYPE, wx.FONTSTYLE_NORMAL,
                                          wx.FONTWEIGHT_NORMAL))
        self.console_ctrl.SetBackgroundColour(wx.BLACK)
        self.console_ctrl.SetForegroundColour(wx.WHITE)
        self.console_ctrl.SetDefaultStyle(wx.TextAttr(wx.WHITE))

        port_label = wx.StaticText(panel, label="Serial port")
        esp_file_label = wx.StaticText(panel, label="ESP Firmware")
        esp_fs_label = wx.StaticText(panel, label="FileSystem")
        flash_file_label = wx.StaticText(panel, label="")

        console_label = wx.StaticText(panel, label="Console")

        fgs.AddMany([
            # Port selection row
            port_label, (serial_boxsizer, 1, wx.EXPAND),
            # ESP Firmware selection row (growable)
            esp_file_label, (esp_file_picker, 1, wx.EXPAND),
            # ESP FileSystem selection row (growable)
            esp_fs_label, (esp_fs_file_picker, 1, wx.EXPAND),
            # Flash firmware button
            flash_file_label, (flash_boxsizer, 1, wx.EXPAND),
            # Console View (growable)
            (console_label, 1, wx.EXPAND), (self.console_ctrl, 1, wx.EXPAND),
        ])
        fgs.AddGrowableRow(4, 1)
        fgs.AddGrowableCol(1, 1)
        hbox.Add(fgs, proportion=2, flag=wx.ALL | wx.EXPAND, border=15)
        panel.SetSizer(hbox)

    def _get_serial_ports(self):
        ports = []
        for port, desc in list_serial_ports():
            ports.append(port)
        if not self._port and ports:
            self._port = ports[0]
        if not ports:
            ports.append("")
        return ports

    # Menu methods
    def _on_exit_app(self, event):
        self.Close(True)

    def log_message(self, message):
        self.console_ctrl.AppendText(message)


class App(wx.App, wx.lib.mixins.inspection.InspectionMixin):
    def OnInit(self):
        wx.SystemOptions.SetOption("mac.window-plain-transition", 1)
        self.SetAppName("z2m partner flasher (Based on NodeMCU PyFlasher)")

        frame = MainFrame(None, "z2m partner flasher (Based on NodeMCU PyFlasher)")
        frame.Show()

        return True


Exit = PyEmbeddedImage(
    "iVBORw0KGgoAAAANSUhEUgAAABAAAAAQCAYAAAAf8/9hAAAABGdBTUEAAK/INwWK6QAAABl0"
    "RVh0U29mdHdhcmUAQWRvYmUgSW1hZ2VSZWFkeXHJZTwAAAN1SURBVHjaYvz//z8DJQAggFhA"
    "xEpGRgaQMX+B+A8DgwYLM1M+r4K8P4+8vMi/P38Y3j18+O7Fs+fbvv7+0w9Uc/kHVG070HKA"
    "AGJBNg0omC5jZtynnpfHJeHkzPDmxQuGf6/eMIj+/yP+9MD+xFPrN8Reu3W3Gqi0D2IXAwNA"
    "AIEN+A/hpWuEBMwwmj6TgUVEjOHTo0cM9y9dZfj76ycDCysrg4K5FYMUvyAL7+pVnYfOXwJp"
    "6wIRAAHECAqDJYyMWpLmpmftN2/mYBEVZ3h38SLD9wcPGP6LioIN/7Z+PQM3UB3vv/8MXB/f"
    "MSzdvv3vpecvzfr+/z8HEEBMYFMYGXM0iwrAmu+sXcvw4OxZhqenTjEwAv3P9OsXw+unTxne"
    "6Osz3Ll3l+HvyzcMVlLSzMBwqgTpBQggsAG8MuKB4r9eM7zfv5PhHxMzg4qLCwPD0ycMDL9/"
    "MzD+/cvw/8kTBgUbGwbB1DSGe1cuMbD8+8EgwMPjCtILEEDgMOCSkhT+t20Nw4v7nxkkNuxm"
    "eLNmFYO0sCgDCwcHAwMzM4Pkl68MLzs7GGS6uhmOCwgxcD2+x8DLysID0gsQQGAD/gH99vPL"
    "dwZGDjaG/0An/z19goHp/z+Gn9dvgoP4/7dPDD9OnGD4+/0bA5uCAsPPW8DA5eACxxxAAIEN"
    "+PDuw/ufirJizE9fMzALCjD8efOO4dHObQx/d29k+PObgeHr268MQta2DCw8fAz/X75k+M/I"
    "xPDh1+9vIL0AAQQOg9dPX2x7w8TDwPL2FcOvI8cYxFs7GFjFpRl+PP/K8O3NVwZuIREGpe5u"
    "hp83rjF8u3iO4RsnO8OzHz8PgvQCBBA4GrsZGfUUtNXPWiuLsny59YxBch3Qdl4uhq/rNzP8"
    "BwYin58PAysbG8MFLy+Gnw9uM5xkYPp38fNX22X//x8DCCAmqD8u3bh6s+Lssy8MrCLcDC/8"
    "3Rl+LVvOwG1syMBrYcbwfetmhmsOdgy/795iuMXEwnDh89c2oJ7jIL0AAQR2wQRgXvgKNAfo"
    "qRIlJfk2NR42Rj5gEmb5+4/h35+/DJ+/fmd4DUyNN4B+v/DlWwcwcTWzA9PXQqBegACCGwAK"
    "ERD+zsBgwszOXirEwe7OzvCP5y/QCx/+/v/26vfv/R///O0GOvkII1AdKxCDDAAIIEZKszNA"
    "gAEA1sFjF+2KokIAAAAASUVORK5CYII=")

Reload = PyEmbeddedImage(
    "iVBORw0KGgoAAAANSUhEUgAAABgAAAAYCAYAAADgdz34AAAABGdBTUEAALGOfPtRkwAAACBj"
    "SFJNAAB6JQAAgIMAAPn/AACA6AAAdTAAAOpgAAA6lwAAF2+XqZnUAAAABmJLR0QA/wD/AP+g"
    "vaeTAAAACXBIWXMAAABIAAAASABGyWs+AAAACXZwQWcAAAAYAAAAGAB4TKWmAAACZUlEQVRI"
    "x7XVT4iXRRgH8M/8Mv9tUFgRZiBESRIhbFAo8kJ0EYoOwtJBokvTxUtBQnUokIjAoCi6+HiR"
    "CNKoU4GHOvQieygMJKRDEUiahC4UtGkb63TY+cnb6/rb3276vQwzzzPf5/9MKqW4kRj8n8s5"
    "53U55y03xEDOeRu+xe5ReqtWQDzAC3gTa3D7KP20nBrknDfhMB7vHH+Dj3AWxyPitxUZyDnv"
    "xsElPL6MT/BiRJwbaaBN6eamlH9yzmvxPp5bRibPYDIizg96pIM2pak2pSexGiLiEr7H3DIM"
    "3IMP/hNBm9It+BDzmGp6oeWcd+BIvdzFRZzGvUOnOtg6qOTrcRxP4ZVmkbxFxDQm8WVPtDMi"
    "tmIDPu7JJocpehnb8F1Tyo/XijsizmMX9teCwq1VNlvrdKFzZeOgTelOvFQPfurV5NE2pc09"
    "I/MR8TqewAxu68hmMd1RPzXAw1hXD9b3nL4bJ9qUdi0SzbF699ee6K9ObU6swoMd4Y42pYmm"
    "lNm6/91C33/RpvQG9jelzHeMnK4F7uK+ur49bNNzHeEdONSmNFH3f9R1gNdwrKZ0UeSc77fQ"
    "CCfxFqSveQA/9HTn8DM2d9I3xBk83ZQy3SNPFqb4JjwTEX9S56BN6SimjI857GtKea+ST+Cx"
    "6synETHssCuv6V5sd/UQXQur8VCb0tqmlEuYi4jPF1PsTvJGvFMjGfVPzOD5ppTPxvHkqseu"
    "Teku7MQm7MEjHfFXeLYp5ey4uRz5XLcpHbAwhH/jVbzblHJ5TG4s/aPN4BT2NKWcXA7xuBFs"
    "wS9NKRdXQr6kgeuBfwEbWdzTvan9igAAADV0RVh0Y29tbWVudABSZWZyZXNoIGZyb20gSWNv"
    "biBHYWxsZXJ5IGh0dHA6Ly9pY29uZ2FsLmNvbS/RLzdIAAAAJXRFWHRkYXRlOmNyZWF0ZQAy"
    "MDExLTA4LTIxVDE0OjAxOjU2LTA2OjAwdNJAnQAAACV0RVh0ZGF0ZTptb2RpZnkAMjAxMS0w"
    "OC0yMVQxNDowMTo1Ni0wNjowMAWP+CEAAAAASUVORK5CYII=")


def main():
    app = App(False)
    app.MainLoop()
