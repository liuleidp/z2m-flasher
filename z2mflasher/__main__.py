from __future__ import print_function

import argparse
from datetime import datetime
import sys
import time

import esptool
import serial

from z2mflasher import const
from z2mflasher.common import ESP32ChipInfo, EsphomeflasherError, chip_run_stub, \
    configure_write_flash_args, detect_chip, detect_flash_size, read_chip_info
from z2mflasher.const import ESP32_DEFAULT_BOOTLOADER_FORMAT, ESP32_DEFAULT_OTA_DATA, \
    ESP32_DEFAULT_PARTITIONS
from z2mflasher.helpers import list_serial_ports

PLATFORMIO_INI = """
[env:esp_wroom_02]
platform = espressif8266
board = esp_wroom_02
framework = arduino
board_build.ldscript = eagle.flash.2m128.ld
"""

def parse_args(argv):
    parser = argparse.ArgumentParser(prog='z2mflasher {}'.format(const.__version__))
    parser.add_argument('-p', '--port',
                        help="Select the USB/COM port for uploading.")
    group = parser.add_mutually_exclusive_group(required=False)
    group.add_argument('--esp8266', action='store_true')
    group.add_argument('--esp32', action='store_true')
    group.add_argument('--upload-baud-rate', type=int, default=460800,
                       help="Baud rate to upload with (not for logging)")
    parser.add_argument('--bootloader',
                        help="(ESP32-only) The bootloader to flash.",
                        default=ESP32_DEFAULT_BOOTLOADER_FORMAT)
    parser.add_argument('--partitions',
                        help="(ESP32-only) The partitions to flash.",
                        default=ESP32_DEFAULT_PARTITIONS)
    parser.add_argument('--otadata',
                        help="(ESP32-only) The otadata file to flash.",
                        default=ESP32_DEFAULT_OTA_DATA)
    parser.add_argument('--no-erase',
                        help="Do not erase flash before flashing",
                        action='store_true')
    parser.add_argument('--show-logs', help="Only show logs", action='store_true')
    parser.add_argument('--offset', help="firmware start position offset", default='0')

    parser.add_argument('--cc253x',
                        help="Flash zigbee CC2530 module though cclib.",
                        action='store_true')
    parser.add_argument('--ssid',
                        help="Fix to connect to AP's ssid.")
    parser.add_argument('--password',
                        help="Fix to connect to AP's password.")
    parser.add_argument('--hostname',
                        help="Set module's hostname.")
    parser.add_argument('--tcpport',
                        help="Serial to Wifi TCP server port.")
    parser.add_argument('--binary', help="The binary image to flash.")

    return parser.parse_args(argv[1:])


def select_port(args):
    if args.port is not None:
        print(u"Using '{}' as serial port.".format(args.port))
        return args.port
    ports = list_serial_ports()
    if not ports:
        raise EsphomeflasherError("No serial port found!")
    if len(ports) != 1:
        print("Found more than one serial port:")
        for port, desc in ports:
            print(u" * {} ({})".format(port, desc))
        print("Please choose one with the --port argument.")
        raise EsphomeflasherError
    print(u"Auto-detected serial port: {}".format(ports[0][0]))
    return ports[0][0]


def show_logs(serial_port):
    print("Showing logs:")
    with serial_port:
        while True:
            try:
                raw = serial_port.readline()
            except serial.SerialException:
                print("Serial port closed!")
                return
            text = raw.decode(errors='ignore')
            line = text.replace('\r', '').replace('\n', '')
            time = datetime.now().time().strftime('[%H:%M:%S]')
            message = time + line
            try:
                print(message)
            except UnicodeEncodeError:
                print(message.encode('ascii', 'backslashreplace'))


def zigbee_flash(serial_port, firmware):
    from z2mflasher.cclib import (CCHEXFile, renderDebugStatus,
        renderDebugConfig, openCCDebugger)

    def read_info():
        # Read zigbee info
        print("Read zigbee info.")
        dbg = openCCDebugger(serial_port, enterDebug=False)
        print("\nDevice information:")
        print(" IEEE Address : %s" % dbg.getSerial())
        print("           PC : %04x" % dbg.getPC())
        print("\nDebug status:")
        renderDebugStatus(dbg.debugStatus)
        print("\nDebug config:")
        renderDebugConfig(dbg.debugConfig)
        print("")
        dbg.close()

    def flash_firmware():
        dbg = openCCDebugger(serial_port, enterDebug=False)
        # Get bluegiga-specific info
        # serial = dbg.getSerial()
        # Parse the HEX file
        hexFile = CCHEXFile(firmware)
        hexFile.load()
        # Display sections & calculate max memory usage
        maxMem = 0
        print("Sections in %s:\n" % firmware)
        print(" Addr.    Size")
        print("-------- -------------")
        for mb in hexFile.memBlocks:
            # Calculate top position
            memTop = mb.addr + mb.size
            if memTop > maxMem:
                maxMem = memTop
            # Print portion
            print(" 0x%04x   %i B " % (mb.addr, mb.size))
        print("")
        # Check for oversize data
        if maxMem > (dbg.chipInfo['flash'] * 1024):
            print("ERROR: Data too bit to fit in chip's memory!")
            print("max mem %x, flash size %x" % (maxMem, dbg.chipInfo['flash'] * 1024))
        # Flashing messages
        print("\nFlashing:")
        # Send chip erase
        if True:
            print(" - Chip erase...")
            dbg.chipErase()
        # Flash memory
        dbg.pauseDMA(False)
        print(" - Flashing %i memory blocks..." % len(hexFile.memBlocks))
        for mb in hexFile.memBlocks:
            # Flash memory block
            print(" -> 0x%04x : %i bytes " % (mb.addr, mb.size))
            dbg.writeCODE( mb.addr, mb.bytes, verify=True, showProgress=True )
        # Done
        dbg.close()

    for i in range(3):
        try:
            read_info()
            break
        except Exception as e:
            print("Read zigbee info failed.")
            if i < 3:
                print("try again.")
                pass
            else:
                print("Flash failed.")
                raise EsphomeflasherError("Can not find zigbee module.");
    flash_firmware()
    print("\nCompleted")
    print("")


def esp_flash(args, port):
    if args.offset:
        print("Firmware start position: {}".format(args.offset))

    try:
        firmware = open(args.binary, 'rb')
    except IOError as err:
        raise EsphomeflasherError("Error opening binary: {}".format(err))
    chip = detect_chip(port, args.esp8266, args.esp32)
    info = read_chip_info(chip)

    print()
    print("Chip Info:")
    print(" - Chip Family: {}".format(info.family))
    print(" - Chip Model: {}".format(info.model))
    if isinstance(info, ESP32ChipInfo):
        print(" - Number of Cores: {}".format(info.num_cores))
        print(" - Max CPU Frequency: {}".format(info.cpu_frequency))
        print(" - Has Bluetooth: {}".format('YES' if info.has_bluetooth else 'NO'))
        print(" - Has Embedded Flash: {}".format('YES' if info.has_embedded_flash else 'NO'))
        print(" - Has Factory-Calibrated ADC: {}".format(
            'YES' if info.has_factory_calibrated_adc else 'NO'))
    else:
        print(" - Chip ID: {:08X}".format(info.chip_id))

    print(" - MAC Address: {}".format(info.mac))

    stub_chip = chip_run_stub(chip)

    if args.upload_baud_rate != 115200:
        try:
            stub_chip.change_baud(args.upload_baud_rate)
        except esptool.FatalError as err:
            raise EsphomeflasherError("Error changing ESP upload baud rate: {}".format(err))

    flash_size = detect_flash_size(stub_chip)
    print(" - Flash Size: {}".format(flash_size))

    mock_args = configure_write_flash_args(info, firmware, flash_size,
                                           args.bootloader, args.partitions,
                                           args.otadata, args.offset)

    print(" - Flash Mode: {}".format(mock_args.flash_mode))
    print(" - Flash Frequency: {}Hz".format(mock_args.flash_freq.upper()))

    try:
        stub_chip.flash_set_parameters(esptool.flash_size_bytes(flash_size))
    except esptool.FatalError as err:
        raise EsphomeflasherError("Error setting flash parameters: {}".format(err))

    if not args.no_erase:
        try:
            esptool.erase_flash(stub_chip, mock_args)
        except esptool.FatalError as err:
            raise EsphomeflasherError("Error while erasing flash: {}".format(err))

    try:
        esptool.write_flash(stub_chip, mock_args)
    except esptool.FatalError as err:
        raise EsphomeflasherError("Error while writing flash: {}".format(err))

    print("Hard Resetting...")
    stub_chip.hard_reset()
    stub_chip._port.close()

def upload_spiffs(args, port):
    def create_file():
        import json
        import os

        config = {}
        f = None
        try:
            if not os.path.exists('data'):
                os.makedirs('data')
            f = open(os.path.join('data', 'config.json'), 'r+')
            config = json.load(f)
            f.seek(0, 0)
            print(f'Exist config {config}')
        except:
            f = open(os.path.join('data', 'config.json'), 'w+')
            print('New config file')

        if args.ssid:
            config['ssid'] = args.ssid
        elif 'ssid' not in config:
            config['ssid'] = ""
        if args.password:
            config['password'] = args.password
        elif 'password' not in config:
            config['password'] = ""
        if args.hostname:
            config['hostname'] = args.hostname
        elif 'hostname' not in config:
            config['hostname'] = ""
        if args.tcpport:
            config['tcpPort'] = int(args.tcpport)
        elif 'tcpPort' not in config:
            config['tcpPort'] = 8880
        # Not used for now.
        if 'mqttServer' not in config:
            config['mqttServer'] = ""
        if 'mqttPort' not in config:
            config['mqttPort'] = 1883
        if 'mqttUser' not in config:
            config['mqttUser'] = ""
        if 'mqttPass' not in config:
            config['mqttPass'] = ""
        if 'mqttClientID' not in config:
            config['mqttClientID'] = ""
        if 'mqttPubTopic' not in config:
            config['mqttPubTopic'] = ""
        if 'mqttSubTopic' not in config:
            config['mqttSubTopic'] = ""
        print(f'New config {config}')
        json.dump(config, f)
        f.flush()
        f.close()

    def create_spiffs_bin():
        import os
        from z2mflasher.spiffsgen import (
            SpiffsBuildConfig, SPIFFS_PAGE_IX_LEN, SPIFFS_BLOCK_IX_LEN, SPIFFS_OBJ_ID_LEN,
            SPIFFS_SPAN_IX_LEN, SpiffsFS)

        with open("spiffs.bin", "wb") as image_file:
            image_size = 110592
            spiffs_build_default = SpiffsBuildConfig(
                256, SPIFFS_PAGE_IX_LEN,
                4096, SPIFFS_BLOCK_IX_LEN,
                1, 32, SPIFFS_OBJ_ID_LEN, SPIFFS_SPAN_IX_LEN,
                True, True, "little",
                True, False)

            spiffs = SpiffsFS(image_size, spiffs_build_default)

            for root, dirs, files in os.walk('./data', followlinks=False):
                for f in files:
                    full_path = os.path.join(root, f)
                    spiffs.create_file("/" + os.path.relpath(full_path, './data').replace("\\", "/"), full_path)

            image = spiffs.to_binary()

            image_file.write(image)

    create_file()
    create_spiffs_bin()
    args.offset = 1966080
    args.binary = "spiffs.bin"
    args.no_erase = True
    esp_flash(args, port)
    return

def run_esphomeflasher(argv):
    args = parse_args(argv)
    port = select_port(args)

    if args.show_logs:
        serial_port = serial.Serial(port, baudrate=115200)
        show_logs(serial_port)
        return

    if args.cc253x:
        print("Flash zigbee module firmware.")
        print("ATTENTION: zigbee firmware must be HEX file.")
        zigbee_flash(port, args.binary)
        return

    if args.esp8266 or args.esp32:
        esp_flash(args, port)

    if args.ssid or args.password or args.hostname or args.tcpport:
        print("Create spiffs for user config.")
        try:
            upload_spiffs(args, port)
        except Exception as e:
            raise EsphomeflasherError(f"Create info spiffs failed. {e}")

    print("Done! Flashing is complete!")
    print()


def main():
    try:
        if len(sys.argv) <= 1:
            from z2mflasher import gui

            return gui.main() or 0
        return run_esphomeflasher(sys.argv) or 0
    except EsphomeflasherError as err:
        msg = str(err)
        if msg:
            print(msg)
        return 1
    except KeyboardInterrupt:
        return 1


if __name__ == "__main__":
    sys.exit(main())
