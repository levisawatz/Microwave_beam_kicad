import machine
from machine import Pin, ADC
import utime

class MAX2870:
    def __init__(self, spi, pin_le, pin_ce, pin_rfen):
        """
        Microwave Beam's MAX2870 Synthesizer/VCO Controller
        Initializes with default values for 5.8GHz, 100MHz fREF, -4dBm Output A.
        """
        self.spi = spi
        self.le = pin_le
        self.ce = pin_ce
        self.rfen = pin_rfen
        self.rf_enabled = False # Track RF state
        
        # Initialize pins
        self.le.init(Pin.OUT, value=1)   # LE idles high
        self.ce.init(Pin.OUT, value=1)   # CE high enables the chip
        self.rfen.init(Pin.OUT, value=0) # RFEN high enables hardware RF output
        
        # MAX2870 Register Array (Defaults for 5.8GHz, Int-N, fREF=100MHz)
        self.registers = [
            0x803A0000, # Reg 0: INT=1, N=58 (0x3A), FRAC=0, ADDR=000
            0x8000FFF9, # Reg 1: CPOC=1, CPL=0, Phase=1, Mod=4095, ADDR=001
            0x80005FA2, # Reg 2: LDS=1, SDN=0, R=1, CP=1111(5.12mA), LDF=1(Int-N), PDP=1, ADDR=010
            0x0000000B, # Reg 3: VAS_SHDN=0 (Auto VCO), ADDR=011
            0x638FF024, # Reg 4: FB=1, DIVA=000 (Div 1), RFA_EN=1, APWR=00 (-4dBm), ADDR=100
            0x01400005  # Reg 5: F01=1 (Auto Int), LD=01 (Digital Lock Detect), ADDR=101
        ]
        
        # Boot sequence: program registers twice with a pause to initialize VAS
        self.power_on_sequence()

    def send_to_device(self, val):
        """
        Handles the SPI protocol to write a 32-bit parameter to the registers.
        """
        data = val.to_bytes(4, 'big')
        self.le.value(0)
        self.spi.write(data)
        self.le.value(1)

    def power_on_sequence(self):
        """
        Programs registers twice to ensure device enabled and VCO selection starts.
        """
        print("Microwave Beam: Initiating power-on sequence...")
        self.ce.value(1)
        
        for _ in range(2):
            for i in range(5, -1, -1):
                self.send_to_device(self.registers[i])
            utime.sleep_ms(20)
            
        print("Microwave Beam: PLL Locked and Loaded!")

    def set_output_a_power(self, power_level):
        """
        Updates the APWR bits in Register 4.
        """
        if power_level < 0 or power_level > 3:
            raise ValueError("Power level must be between 0 and 3")
            
        reg4 = self.registers[4]
        reg4 &= ~(0b11 << 3) 
        reg4 |= (power_level << 3)
        self.registers[4] = reg4
        
        self.send_to_device(self.registers[4])
        print(f"Microwave Beam: Output A power adjusted to setting {power_level}.")

    def toggle_rf(self):
        """
        Toggles the RF output using the hardware RFEN pin.
        """
        self.rf_enabled = not self.rf_enabled
        self.rfen.value(1 if self.rf_enabled else 0)
        print(f"Microwave Beam: RF Output {'ENABLED' if self.rf_enabled else 'DISABLED'}")


# ==========================================
# Main Execution for Raspberry Pi Pico
# ==========================================
if __name__ == '__main__':
    PIN_SCK  = 2
    PIN_MOSI = 3
    PIN_LE   = 5
    PIN_CE   = 6
    PIN_RFEN = 7
    PIN_DCDCEN = 8
    PIN_P_CTRL1 = 12
    PIN_P_CTRL2 = 11
    PIN_BTN1 = 0
    PIN_BTN2 = 1


    spi0 = machine.SPI(0, baudrate=10_000_000, polarity=0, phase=0,
                       sck=Pin(PIN_SCK), mosi=Pin(PIN_MOSI))

    le_pin = Pin(PIN_LE)
    ce_pin = Pin(PIN_CE)
    rfen_pin = Pin(PIN_RFEN)
    led_pin = Pin(25, Pin.OUT)
    DCDC_en_pin = Pin(PIN_DCDCEN, Pin.OUT, value=0)
    utime.sleep_ms(1000)
    DCDC_en_pin.value(1)
    
    vco = MAX2870(spi=spi0, pin_le=le_pin, pin_ce=ce_pin, pin_rfen=rfen_pin)
    
    # Inputs
    button_1 = Pin(0, Pin.IN, Pin.PULL_UP)
    button_2 = Pin(1, Pin.IN, Pin.PULL_UP)

    # Outputs
    phase_ctrl_1 = Pin(12, Pin.OUT)
    phase_ctrl_2 = Pin(11, Pin.OUT)

    # ADCs
    ADC_stage_1_power = ADC(Pin(26))
    ADC_stage_2_power = ADC(Pin(27))
    ADC_coupled_power = ADC(Pin(28))
    
    # ------------------------------------------
    # Main Loop / Button Logic
    # ------------------------------------------
    
    # Phase control definitions
    phase_sequence = [(0, 0), (0, 1), (1, 0), (1, 1)]
    current_phase_idx = 0
    
    # Set initial phase state to 00
    phase_ctrl_1.value(phase_sequence[current_phase_idx][0])
    phase_ctrl_2.value(phase_sequence[current_phase_idx][1])

    # Variables for button debouncing / edge detection
    last_btn1_state = 1
    last_btn2_state = 1
    debounce_delay = 50 # milliseconds

    print("System ready. Waiting for input...")

    while True:
        btn1_state = button_1.value()
        btn2_state = button_2.value()
        led_pin.value(DCDC_en_pin.value())
        

        # Check for Button 1 (RF Toggle) falling edge
        if btn1_state == 0 and last_btn1_state == 1:
            vco.toggle_rf()
            utime.sleep_ms(debounce_delay)


        # Check for Button 2 (Phase Toggle) falling edge
        if btn2_state == 0 and last_btn2_state == 1:
            # Advance to next phase state and wrap around
            current_phase_idx = (current_phase_idx + 1) % len(phase_sequence)
            p1_val, p2_val = phase_sequence[current_phase_idx]
            
            phase_ctrl_1.value(p1_val)
            phase_ctrl_2.value(p2_val)
            print(f"Phase Control set to: {p1_val}{p2_val}")
            
            utime.sleep_ms(debounce_delay)

            DCDC_en_pin.low()
            led_pin.low()
            utime.sleep_ms(1000)
            led_pin.high()
            DCDC_en_pin.high()

        # Update last states
        last_btn1_state = btn1_state
        last_btn2_state = btn2_state

        # Small delay to prevent pegging the CPU
        utime.sleep_ms(10)