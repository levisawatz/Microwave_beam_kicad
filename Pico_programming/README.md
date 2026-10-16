# Microwave Beam Pico control

`MWB_pico_control.py` is the Pico firmware. Copy it to the Pico filesystem as
`main.py`; it starts with RF disabled and accepts USB-serial commands from
`MWB_gui.py`.

On the control PC, install the one non-standard dependency and start the GUI:

```powershell
py -m pip install pyserial
py .\MWB_gui.py
```

Select the Pico COM port, connect, then set the RF enable, MAX2870 output-A
power, and beam angle. The monitor panel samples GP26/GP27/GP28 twice per
second.

The displayed SE5004L estimates are interpolated from the provided 5850 MHz
VDET plot. The LTC5531 estimate is interpolated from its 6000 MHz / 25 C plot,
then has 20 dB added to report power before the stated -20 dB directional
coupler. These are useful estimated readings, not calibrated power-meter
measurements. Change `COUPLER_DB` and/or the curve tables in `MWB_gui.py` once
you have a bench calibration for the assembled board.
