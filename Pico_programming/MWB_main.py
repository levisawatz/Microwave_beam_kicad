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
        
        # Initialize pins
        self.le.init(Pin.OUT, value=1) # LE idles high
        self.ce.init(Pin.OUT, value=1) # CE high enables the chip
        self.rfen.init(Pin.OUT, value=1) # RFEN high enables hardware RF output
        
        # MAX2870 Register Array (Defaults for 5.8GHz, Int-N, fREF=100MHz)
        # Register values are calculated based on the MAX2870 datasheet specifications.
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
        Data is latched into the shift register on the rising edge of CLK.
        At the rising edge of LE, data is latched into the addressed register.
        """
        # Convert the 32-bit integer to a 4-byte array (MSB first)
        data = val.to_bytes(4, 'big')
        
        # Pull Latch Enable (LE) low to start shifting
        self.le.value(0)
        
        # Send data over SPI
        self.spi.write(data)
        
        # Pulse Latch Enable (LE) high to latch the data into the register
        self.le.value(1)

    def power_on_sequence(self):
        """
        Upon power-up, the registers should be programmed twice with at least a 
        20ms pause between writes to ensure the device is enabled and the VCO 
        selection process starts.
        """
        print("Microwave Beam: Initiating power-on sequence...")
        self.ce.value(1) # Ensure chip is enabled
        
        for _ in range(2):
            # Programming order must be 0x05, 0x04, 0x03, 0x02, 0x01, and 0x00
            for i in range(5, -1, -1):
                self.send_to_device(self.registers[i])
            utime.sleep_ms(20)
            
        print("Microwave Beam: PLL Locked and Loaded!")

    def set_output_a_power(self, power_level):
        """
        Updates the APWR bits in Register 4.
        power_level: 0 = -4dBm, 1 = -1dBm, 2 = +2dBm, 3 = +5dBm
        """
        if power_level < 0 or power_level > 3:
            raise ValueError("Power level must be between 0 and 3")
            
        # Clear current APWR bits (bits 4:3) and set new power level
        reg4 = self.registers[4]
        reg4 &= ~(0b11 << 3) 
        reg4 |= (power_level << 3)
        self.registers[4] = reg4
        
        # Send updated register 4 to the device
        self.send_to_device(self.registers[4])
        print(f"Microwave Beam: Output A power adjusted to setting {power_level}.")


# ==========================================
# Main Execution for Raspberry Pi Pico
# ==========================================
if __name__ == '__main__':
    # Pin definitions based on your request
    PIN_SCK  = 2
    PIN_MOSI = 3
    PIN_LE   = 5
    PIN_CE   = 6
    PIN_RFEN = 7
    
    # Configure hardware SPI on the Pico
    # The MAX2870 latches data on the rising edge of CLK, MSB first
    spi0 = machine.SPI(0, baudrate=10_000_000, polarity=0, phase=0,
                       sck=Pin(PIN_SCK), mosi=Pin(PIN_MOSI))

    # Initialize control pins
    le_pin = Pin(PIN_LE)
    ce_pin = Pin(PIN_CE)
    rfen_pin = Pin(PIN_RFEN)
    
    # Instantiate the VCO controller
    # The __init__ function automatically loads the 5.8GHz defaults!
    vco = MAX2870(spi=spi0, pin_le=le_pin, pin_ce=ce_pin, pin_rfen=rfen_pin)
    button_1 = Pin(0, Pin.IN, Pin.PULL_UP)
    button_2 = Pin(1, Pin.IN, Pin.PULL_UP)
    ADC_stage_1_power = ADC(Pin(26))
    ADC_stage_2_power = ADC(Pin(27))
    ADC_coupled_power = ADC(Pin(28))
    # Example: Change power level to +5dBm dynamically
    # vco.set_output_a_power(3)