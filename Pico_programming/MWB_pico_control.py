"""USB-serial control firmware for the Microwave Beam Pico.

Save this file on the Pico as ``main.py``.  The USB serial interface accepts
newline-terminated ASCII commands and reports machine-readable JSON lines:

    RF 0|1                 Disable or enable RF output
    POWER 0|1|2|3          MAX2870 Output-A setting (-4, -1, +2, +5 dBm)
    ANGLE -20|0|30|-45     Select the corresponding phase-control state
    MEASURE                Read all power-monitor ADC inputs
    STATE                  Read the selected settings without sampling ADCs
    PING                   Check the connection

The desktop MWB_gui.py application implements this protocol.  RF output is
disabled at boot, so reconnecting or resetting the Pico has a safe default.
"""

import machine
from machine import ADC, Pin
import sys
import time
import uselect
import ujson


ADC_REFERENCE_VOLTAGE = 3.3
POWER_LEVELS_DBM = (-4, -1, 2, 5)
ANGLE_STATES = {
    -20: (0, 0),
    0: (0, 1),
    30: (1, 0),
    -45: (1, 1),
}


class MAX2870:
    """Minimal MAX2870 controller for the fixed 5.8 GHz configuration."""

    def __init__(self, spi, pin_le, pin_ce, pin_rfen):
        self.spi = spi
        self.le = pin_le
        self.ce = pin_ce
        self.rfen = pin_rfen
        self.le.init(Pin.OUT, value=1)
        self.ce.init(Pin.OUT, value=1)
        self.rfen.init(Pin.OUT, value=0)  # RF starts disabled.
        self.registers = [
            0x801D0000,  # R0: 5.8 GHz, 100 MHz reference
            0x8000FFF9,
            0x80005FC2,
            0x0000000B,
            0x638FF024,  # R4, Output A enabled, -4 dBm setting
            0x01400005,
        ]
        self.power_on_sequence()

    def send_to_device(self, value):
        self.le.value(0)
        self.spi.write(value.to_bytes(4, "big"))
        self.le.value(1)

    def power_on_sequence(self):
        self.ce.value(1)
        for _ in range(2):
            for register in range(5, -1, -1):
                self.send_to_device(self.registers[register])
            # Required VAS start-up settling time.
            time.sleep_ms(20)

    def set_output_a_power(self, level):
        if level not in range(4):
            raise ValueError("POWER must be 0, 1, 2, or 3")
        self.registers[4] &= ~(0b11 << 3)
        self.registers[4] |= level << 3
        self.send_to_device(self.registers[4])

    def set_rf_enable(self, enabled):
        self.rfen.value(1 if enabled else 0)


def read_adc(adc):
    """Take a short average to make the GUI readings less jumpy."""
    total = 0
    for _ in range(16):
        total += adc.read_u16()
    raw = total // 16
    return {"raw": raw, "volts": round(raw * ADC_REFERENCE_VOLTAGE / 65535, 4)}


def main():
    spi0 = machine.SPI(0, baudrate=10_000_000, polarity=0, phase=0,
                       sck=Pin(2), mosi=Pin(3))
    vco = MAX2870(spi0, Pin(5), Pin(6), Pin(7))

    phase_ctrl_1 = Pin(12, Pin.OUT, value=0)
    phase_ctrl_2 = Pin(11, Pin.OUT, value=0)
    adc_stage_1 = ADC(Pin(26))  # SE5004L stage 1 VDET
    adc_stage_2 = ADC(Pin(27))  # SE5004L stage 2 VDET
    adc_coupled = ADC(Pin(28))  # LTC5531 output after the -20 dB coupler

    state = {"rf_enabled": False, "power_level": 0, "angle_deg": -20}
    vco.set_output_a_power(state["power_level"])
    vco.set_rf_enable(False)

    poller = uselect.poll()
    poller.register(sys.stdin, uselect.POLLIN)

    def apply_angle(angle):
        control_1, control_2 = ANGLE_STATES[angle]
        phase_ctrl_1.value(control_1)
        phase_ctrl_2.value(control_2)
        state["angle_deg"] = angle

    def send(kind, payload=None):
        if payload is None:
            print(kind)
        else:
            print(kind + " " + ujson.dumps(payload))

    apply_angle(-20)
    send("READY", {"firmware": "MWB_pico_control", "adc_reference_v": ADC_REFERENCE_VOLTAGE})

    while True:
        if not poller.poll(25):
            continue
        line = sys.stdin.readline()
        if not line:
            continue
        fields = line.strip().upper().split()
        if not fields:
            continue
        try:
            command = fields[0]
            if command == "PING":
                send("OK", {"pong": True})
            elif command == "STATE":
                send("STATE", state)
            elif command == "MEASURE":
                send("MEASURE", {
                    "stage_1": read_adc(adc_stage_1),
                    "stage_2": read_adc(adc_stage_2),
                    "coupled": read_adc(adc_coupled),
                    "state": state,
                })
            elif command == "RF" and len(fields) == 2 and fields[1] in ("0", "1"):
                state["rf_enabled"] = fields[1] == "1"
                vco.set_rf_enable(state["rf_enabled"])
                send("OK", state)
            elif command == "POWER" and len(fields) == 2:
                level = int(fields[1])
                vco.set_output_a_power(level)
                state["power_level"] = level
                send("OK", state)
            elif command == "ANGLE" and len(fields) == 2:
                angle = int(fields[1])
                if angle not in ANGLE_STATES:
                    raise ValueError("ANGLE must be -20, 0, 30, or -45")
                apply_angle(angle)
                send("OK", state)
            else:
                raise ValueError("unknown or malformed command")
        except Exception as error:
            send("ERROR", {"message": str(error)})


main()
