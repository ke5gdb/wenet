from smbus2 import SMBus
import ads1115

class WenetPiHAT():
    """
    Class for polling power and temperature data from ADS1115 ADC
    """
    def __init__(self, i2c=1, address=0x48):
        bus = SMBus(i2c)
        # Initialize ADC with gain of 1
        self.adc = ads1115.ADS1115(bus, address, 1)

    def read(self):
        # 0.0001875 = 6.144 / 32768

        batt_v = self.adc.read(4,0) * 5000.0 * 0.0001875 # batt voltage in mV
        batt_i = self.adc.read(4,1) * 1000.0 * 0.0001875 # batt current in mA

        temp =  self.adc.read(4,0) * 100.0 * 0.0001875 # LM35 temperature (10mV/decC)

        return  {'batt_v': batt_v, 'batt_i': batt_i,  'aux_temp': temp}