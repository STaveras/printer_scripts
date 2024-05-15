import serial
import time
import sys

# Constants
SERIAL_PORT = '/dev/ttyACM0'  # Change to your actual serial port
BAUD_RATE = 115200
TIMEOUT = 10
BED_TEMP_TARGET = 65
COARSE_STEP = 0.2
FINE_STEP = 0.01
SAFE_Z_HEIGHT = 7.0
PROBE_DEPLOY_CMD = "M280 P0 S10"
PROBE_STOW_CMD = "M280 P0 S160"

class PrinterController:
    def __init__(self, port, baud_rate, timeout):
        self.ser = serial.Serial(port, baud_rate, timeout=timeout)
        self.z_height = SAFE_Z_HEIGHT
        self.trigger_height = 0.0

    def message(self, msg):
        self.send_command(f"M117 {msg}")
        print(msg)

    def send_command(self, command, timeout=5):
        """Send command to the printer and wait for the response."""
        self.ser.reset_input_buffer()
        self.ser.write((command + '\n').encode())
        time.sleep(0.1)
        responses = []
        start_time = time.time()
        while True:
            if self.ser.in_waiting > 0:
                response = self.ser.readline().decode().strip()
                responses.append(response)
                if response.startswith("ok"):
                    break
            if time.time() - start_time > timeout:
                break
        print(f"{command}: {responses}")
        return '\n'.join(responses)

    def get_probe_status(self):
        response = self.send_command("M119")
        for line in response.split('\n'):
            if "z_probe:" in line:
                status = line.split(":")[1].strip().lower()
                print(status)
                return status
        return None

    def probe_triggered(self):
        return self.get_probe_status() == "triggered"

    def wait_for_temperature(self, target_temp):
        while True:
            response = self.send_command("M105")  # Request temperature
            if response.startswith("ok T:"):
                current_temp = float(response.split(":")[2].split()[0])
                if current_temp >= target_temp:
                    break
            time.sleep(1)

    def coarse_probe(self):
        self.message("Starting coarse range check...")
        while not self.probe_triggered() and self.z_height > 0:
            self.send_command(f"G0 Z-{COARSE_STEP}")
            self.z_height -= COARSE_STEP
            print(self.z_height)
        if self.probe_triggered():
            self.message("Probe triggered!")
            response = self.send_command("M114")
            self.trigger_height = float(response.split('Z:')[1].split()[0])
        self.message(f"Finished. Current Z height: {self.z_height}")

    def fine_probe(self):
        z_heights = []
        for run in range(3):
            self.message(f"Starting fine range check (run {run + 1}/3)...")
            self.z_height = self.trigger_height + COARSE_STEP;
            self.send_command("G90")
            self.send_command(f"G0 F500 Z{SAFE_Z_HEIGHT}")
            time.sleep(3)
            self.send_command(PROBE_DEPLOY_CMD)
            self.send_command(f"G0 Z{self.z_height}")
            self.send_command("G91")
            while not self.probe_triggered() and self.z_height > 0:
                self.send_command(f"G1 Z-{FINE_STEP} F50")
                self.z_height -= FINE_STEP
                print(self.z_height)
            z_heights.append(self.z_height)
            self.send_command(PROBE_STOW_CMD)
            time.sleep(2.190)
        final_z_height = sum(z_heights) / len(z_heights)
        self.message(f"Finished. Final Z-Probe Offset: {final_z_height}")
        return final_z_height

    def run(self):
        try:
            self.message("Starting Z-Probe calibration...")
            self.send_command("M420 S0 Z0")
            self.send_command("G28")
            time.sleep(10)
            self.send_command(f"M140 S{BED_TEMP_TARGET}")
            self.message("Heating bed...")
            self.wait_for_temperature(BED_TEMP_TARGET)
            self.send_command("G90")
            self.send_command(f"G0 F500 Z{SAFE_Z_HEIGHT}")
            time.sleep(1)
            self.send_command("G0 F5000 X156.3 Y124.4")
            time.sleep(3)
            self.send_command(PROBE_DEPLOY_CMD)
            self.send_command("G91")
            self.coarse_probe()
            self.send_command(PROBE_STOW_CMD)
            time.sleep(2.190)
            self.send_command("G90")
            self.send_command(f"G0 F500 Z{SAFE_Z_HEIGHT}")
            time.sleep(3)
            final_z_height = self.fine_probe()
            self.send_command(f"M851 Z-{final_z_height}")
            self.message(f"Z-Probe offset set to: -{final_z_height}")
            self.send_command("M140 S0")
            time.sleep(1)
            self.send_command("M500")
            time.sleep(5)
        except serial.SerialException as e:
            print(f"Serial communication error: {e}")
        except Exception as e:
            print(f"Error occurred: {e}")
        finally:
            self.ser.close()
            sys.exit()

if __name__ == "__main__":
    printer = PrinterController(SERIAL_PORT, BAUD_RATE, TIMEOUT)
    printer.run()
