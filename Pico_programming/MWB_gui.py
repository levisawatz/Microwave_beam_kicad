"""Desktop control panel for MWB_pico_control.py.

Requires Python 3 with tkinter (normally included on Windows) and pyserial:
    py -m pip install pyserial
"""

import json
import queue
import threading
import time
import tkinter as tk
from tkinter import messagebox, ttk

try:
    import serial
    from serial.tools import list_ports
except ImportError:
    serial = None
    list_ports = None


POWER_LEVELS = {0: "-4 dBm", 1: "-1 dBm", 2: "+2 dBm", 3: "+5 dBm"}
# Left-to-right order on the direction slider.
DIRECTION_ANGLES = (-45, -20, 0, 30)
COUPLER_DB = 20.0

# Digitized estimates from the supplied curves.  The SE5004L values use the
# 5850 MHz (blue) trace.  The LTC5531 points use the 6000 MHz, 25 C trace.
SE5004L_5850MHZ = [
    (0.305, 3), (0.312, 5), (0.320, 7), (0.335, 9), (0.355, 11),
    (0.380, 13), (0.420, 15), (0.470, 17), (0.530, 19), (0.610, 21),
    (0.720, 23), (0.840, 25), (1.010, 27), (1.210, 29),
]
LTC5531_6000MHZ_25C = [
    (0.120, -30), (0.130, -26), (0.150, -22), (0.180, -18),
    (0.240, -14), (0.340, -10), (0.530, -6), (0.800, -2),
    (1.350, 2), (2.300, 6), (3.550, 10),
]


def interpolate(points, voltage):
    """Linear interpolation with endpoint clamping for a digitized curve."""
    if voltage <= points[0][0]:
        return points[0][1]
    if voltage >= points[-1][0]:
        return points[-1][1]
    for (v0, p0), (v1, p1) in zip(points, points[1:]):
        if voltage <= v1:
            return p0 + (voltage - v0) * (p1 - p0) / (v1 - v0)
    return points[-1][1]


class PicoConnection:
    def __init__(self):
        self.port = None
        self.responses = queue.Queue()
        self.reader = None
        self.running = False

    def connect(self, port_name):
        if serial is None:
            raise RuntimeError("pyserial is not installed. Run: py -m pip install pyserial")
        self.close()
        self.port = serial.Serial(port_name, 115200, timeout=0.2)
        self.running = True
        self.reader = threading.Thread(target=self._read_lines, daemon=True)
        self.reader.start()
        self.send("PING")

    def close(self):
        self.running = False
        if self.port:
            self.port.close()
        self.port = None

    def _read_lines(self):
        while self.running and self.port:
            try:
                line = self.port.readline().decode("utf-8", errors="replace").strip()
                if line:
                    self.responses.put(line)
            except Exception as error:
                self.responses.put("ERROR {\"message\": \"%s\"}" % error)
                break

    def send(self, command):
        if not self.port or not self.port.is_open:
            raise RuntimeError("Pico is not connected")
        self.port.write((command + "\n").encode("ascii"))


class MWBGui(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Microwave Beam Control")
        self.resizable(False, False)
        self.connection = PicoConnection()
        self.measurement_pending = False
        self.port_var = tk.StringVar()
        self.status_var = tk.StringVar(value="Disconnected")
        self.rf_var = tk.StringVar(value="RF output: OFF")
        self.power_var = tk.StringVar(value=POWER_LEVELS[0])
        self.direction_index = tk.IntVar(value=DIRECTION_ANGLES.index(0))
        self.direction_text = tk.StringVar(value="0°")
        self.requested_frequency_var = tk.StringVar(value="5800")
        self.actual_frequency_var = tk.StringVar(value="--")
        self.measurement_vars = {name: (tk.StringVar(value="-- V"), tk.StringVar(value="-- dBm"))
                                 for name in ("Stage 1 (SE5004L)", "Stage 2 (SE5004L)", "Coupled output (LTC5531)")}
        self._build_ui()
        self.refresh_ports()
        self.after(100, self.process_responses)
        self.after(500, self.poll_measurement)
        self.protocol("WM_DELETE_WINDOW", self.on_close)

    def _build_ui(self):
        padding = {"padx": 8, "pady": 5}
        connection = ttk.LabelFrame(self, text="Pico connection", padding=8)
        connection.grid(row=0, column=0, sticky="ew", **padding)
        self.port_combo = ttk.Combobox(connection, textvariable=self.port_var, width=24, state="readonly")
        self.port_combo.grid(row=0, column=0, padx=(0, 5))
        ttk.Button(connection, text="Refresh", command=self.refresh_ports).grid(row=0, column=1, padx=3)
        self.connect_button = ttk.Button(connection, text="Connect", command=self.toggle_connection)
        self.connect_button.grid(row=0, column=2, padx=3)
        ttk.Label(connection, textvariable=self.status_var).grid(row=1, column=0, columnspan=3, sticky="w", pady=(5, 0))

        control = ttk.LabelFrame(self, text="RF controls", padding=8)
        control.grid(row=1, column=0, sticky="ew", **padding)
        self.rf_button = ttk.Button(control, textvariable=self.rf_var, command=self.toggle_rf)
        self.rf_button.grid(row=0, column=0, rowspan=3, padx=(0, 20))
        ttk.Label(control, text="Synthesizer power").grid(row=0, column=1, sticky="w")
        power_combo = ttk.Combobox(control, textvariable=self.power_var, values=list(POWER_LEVELS.values()), width=10, state="readonly")
        power_combo.grid(row=1, column=1, sticky="w")
        power_combo.bind("<<ComboboxSelected>>", self.set_power)
        ttk.Label(control, text="VCO / PLL frequency (MHz)").grid(row=0, column=2, sticky="w", padx=(22, 0))
        frequency_frame = ttk.Frame(control)
        frequency_frame.grid(row=1, column=2, sticky="w", padx=(22, 0))
        frequency_entry = ttk.Entry(frequency_frame, textvariable=self.requested_frequency_var, width=10)
        frequency_entry.pack(side="left")
        frequency_entry.bind("<Return>", self.set_frequency)
        ttk.Button(frequency_frame, text="Set", command=self.set_frequency).pack(side="left", padx=(5, 0))
        actual_frequency_frame = ttk.Frame(control)
        actual_frequency_frame.grid(row=2, column=2, sticky="w", padx=(22, 0), pady=(8, 0))
        ttk.Label(actual_frequency_frame, text="Actual PLL:").pack(side="left")
        ttk.Entry(actual_frequency_frame, textvariable=self.actual_frequency_var, width=10,
                  state="readonly").pack(side="left", padx=(5, 2))
        ttk.Label(actual_frequency_frame, text="MHz").pack(side="left")
        ttk.Label(control, text="Beam direction (left → right)").grid(row=2, column=1, sticky="w", pady=(8, 0))
        direction_frame = ttk.Frame(control)
        direction_frame.grid(row=3, column=1, columnspan=2, sticky="w")
        tk.Scale(direction_frame, from_=0, to=3, resolution=1, orient="horizontal",
                 showvalue=False, length=150, variable=self.direction_index,
                 command=self.set_direction).grid(row=0, column=0, sticky="w")
        ttk.Label(direction_frame, text="−45°       −20°          0°        +30°",
                  textvariable=None).grid(row=1, column=0, sticky="w")
        ttk.Label(direction_frame, textvariable=self.direction_text).grid(row=0, column=1, padx=(8, 0))

        monitor = ttk.LabelFrame(self, text="Power-monitor readings (auto-refreshes twice per second)", padding=8)
        monitor.grid(row=2, column=0, sticky="ew", **padding)
        ttk.Label(monitor, text="Monitor", width=26).grid(row=0, column=0, sticky="w")
        ttk.Label(monitor, text="ADC voltage", width=16).grid(row=0, column=1, sticky="w")
        ttk.Label(monitor, text="Estimated RF power").grid(row=0, column=2, sticky="w")
        for row, (name, (voltage, power)) in enumerate(self.measurement_vars.items(), start=1):
            ttk.Label(monitor, text=name).grid(row=row, column=0, sticky="w", pady=2)
            ttk.Label(monitor, textvariable=voltage).grid(row=row, column=1, sticky="w")
            ttk.Label(monitor, textvariable=power).grid(row=row, column=2, sticky="w")
        ttk.Label(monitor, text="Coupled output includes +%.1f dB correction for the directional coupler." % COUPLER_DB,
                  foreground="#555555").grid(row=4, column=0, columnspan=3, sticky="w", pady=(6, 0))

    def refresh_ports(self):
        ports = [port.device for port in list_ports.comports()] if list_ports else []
        self.port_combo["values"] = ports
        if ports and self.port_var.get() not in ports:
            self.port_var.set(ports[0])

    def toggle_connection(self):
        if self.connection.port:
            self.connection.close()
            self.status_var.set("Disconnected")
            self.connect_button.config(text="Connect")
            return
        try:
            self.connection.connect(self.port_var.get())
            self.status_var.set("Connected to %s; checking Pico…" % self.port_var.get())
            self.connect_button.config(text="Disconnect")
        except Exception as error:
            messagebox.showerror("Cannot connect", str(error))

    def send(self, command):
        try:
            self.connection.send(command)
        except RuntimeError as error:
            self.status_var.set(str(error))

    def toggle_rf(self):
        self.send("RF " + ("0" if "ON" in self.rf_var.get() else "1"))

    def set_power(self, _event=None):
        chosen = next(level for level, label in POWER_LEVELS.items() if label == self.power_var.get())
        self.send("POWER %d" % chosen)

    def set_direction(self, _value=None):
        angle = DIRECTION_ANGLES[self.direction_index.get()]
        self.direction_text.set("%+d°" % angle)
        self.send("ANGLE %d" % angle)

    def set_frequency(self, _event=None):
        try:
            frequency_mhz = float(self.requested_frequency_var.get())
        except ValueError:
            messagebox.showerror("Invalid frequency", "Enter a frequency in MHz, for example 5800.")
            return
        if not 3000.0 <= frequency_mhz <= 6000.0:
            messagebox.showerror("Invalid frequency", "The board's VCO control range is 3000 to 6000 MHz.")
            return
        self.send("FREQ %.6f" % frequency_mhz)

    def poll_measurement(self):
        if self.connection.port and not self.measurement_pending:
            self.send("MEASURE")
            self.measurement_pending = True
        self.after(500, self.poll_measurement)

    def process_responses(self):
        while not self.connection.responses.empty():
            line = self.connection.responses.get_nowait()
            kind, _, text = line.partition(" ")
            try:
                payload = json.loads(text) if text else {}
            except json.JSONDecodeError:
                continue  # Ignore MicroPython prompt/start-up text.
            if kind == "MEASURE":
                self.measurement_pending = False
                self.update_measurements(payload)
                self.apply_state(payload.get("state", {}))
            elif kind in ("OK", "STATE"):
                self.apply_state(payload)
                self.status_var.set("Connected to %s" % self.port_var.get())
            elif kind == "READY":
                self.status_var.set("Pico ready on %s" % self.port_var.get())
            elif kind == "ERROR":
                self.measurement_pending = False
                self.status_var.set("Pico error: " + payload.get("message", "unknown error"))
        self.after(100, self.process_responses)

    def apply_state(self, state):
        if "rf_enabled" in state:
            self.rf_var.set("RF output: " + ("ON" if state["rf_enabled"] else "OFF"))
        if "power_level" in state:
            self.power_var.set(POWER_LEVELS.get(state["power_level"], "Unknown"))
        if "angle_deg" in state:
            angle = state["angle_deg"]
            if angle in DIRECTION_ANGLES:
                self.direction_index.set(DIRECTION_ANGLES.index(angle))
                self.direction_text.set("%+d°" % angle)
        if "frequency_mhz" in state:
            self.actual_frequency_var.set("%.4f" % state["frequency_mhz"])

    def update_measurements(self, payload):
        monitors = (("Stage 1 (SE5004L)", "stage_1", SE5004L_5850MHZ, 0.0),
                    ("Stage 2 (SE5004L)", "stage_2", SE5004L_5850MHZ, 0.0),
                    ("Coupled output (LTC5531)", "coupled", LTC5531_6000MHZ_25C, COUPLER_DB))
        for label, key, curve, correction in monitors:
            volts = payload[key]["volts"]
            estimated = interpolate(curve, volts) + correction
            voltage_var, power_var = self.measurement_vars[label]
            voltage_var.set("%.3f V" % volts)
            power_var.set("%.1f dBm" % estimated)

    def on_close(self):
        self.connection.close()
        self.destroy()


if __name__ == "__main__":
    MWBGui().mainloop()
