import serial
import time
import sys
import argparse

# Constants
SERIAL_PORT = '/dev/ttyACM0'  # Change to your actual serial port
BAUD_RATE = 115200
TIMEOUT = 10
COARSE_STEP = 0.2
FINE_STEP = 0.01
SAFE_Z_HEIGHT = 7.0
DEFAULT_BED_TARGET_TEMP = 65
PROBE_DEPLOY_CMD = "M280 P0 S10"
PROBE_STOW_CMD = "M280 P0 S160"
PROBE_STOW_DELAY = 2.190

class PrinterController:
    def __init__(self, port, baud_rate, timeout):
        self.ser = serial.Serial(port, baud_rate, timeout=timeout)
        self.z_height = SAFE_Z_HEIGHT
        self.trigger_height = 0.0

    def message(self, msg):
        self.send_command(f"M117 {msg}")

    def send_command(self, command, timeout=5):
        """Send command to the printer and wait for the response."""
        self.ser.reset_input_buffer()
        self.ser.write((command + '\n').encode())
        time.sleep(0.1)
        responses = []
        start_time = time.time()
        print(f"{command}:")
        while True:
            if self.ser.in_waiting > 0:
                response = self.ser.readline().decode().strip()
                responses.append(response)
                print(f"{response}")
                if response.startswith("ok"):
                    break
            if time.time() - start_time > timeout:
                break
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
        self.send_command(PROBE_DEPLOY_CMD)
        self.send_command("G91")
        while not self.probe_triggered() and self.z_height > 0:
            self.send_command(f"G0 Z-{COARSE_STEP}")
            self.z_height -= COARSE_STEP
            print(self.z_height)
        if self.probe_triggered():
            self.message("Probe triggered!")
            response = self.send_command("M114")
            self.trigger_height = float(response.split('Z:')[1].split()[0])
            self.send_command(PROBE_STOW_CMD)
            time.sleep(PROBE_STOW_DELAY)
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
            time.sleep(PROBE_STOW_DELAY)
        final_z_height = sum(z_heights) / len(z_heights)
        self.message(f"Finished. Final Z-Probe Offset: {final_z_height}")
        return final_z_height

    def run(self, bed_temp_target, disable_bed, run_g29):
        try:
            self.message("Starting Z-Probe calibration...")
            self.send_command("M420 S0 Z0")
            self.send_command("G28")
            time.sleep(10)
            self.send_command(f"M140 S{bed_temp_target}")
            self.message("Heating bed...")
            self.wait_for_temperature(bed_temp_target)
            time.sleep(3)
            self.send_command("G90")
            self.send_command(f"G0 F500 Z{SAFE_Z_HEIGHT}")
            time.sleep(1)
            self.send_command("G0 F5000 X156.3 Y124.4")
            time.sleep(3)
            self.coarse_probe()
            self.send_command("G90")
            self.send_command(f"G0 F500 Z{SAFE_Z_HEIGHT}")
            time.sleep(3)
            final_z_height = self.fine_probe()
            self.send_command(f"M851 Z-{final_z_height}")
            if disable_bed:
                self.send_command("M140 S0")
                time.sleep(1)
            if run_g29:
                self.send_command("G29 P1", timeout=600) # This is usually around how long it takes for a full repopulate
                for r in range(2): # For two axes (X, Y)
                    self.send_command("G29 P3")
                    print(r)
            time.sleep(1)
            self.send_command("M500")
            time.sleep(5)
            self.message(f"Probe Z-offset set to: -{final_z_height}")
        except serial.SerialException as e:
            print(f"Serial communication error: {e}")
        except Exception as e:
            print(f"Error occurred: {e}")
        finally:
            self.ser.close()
            sys.exit()

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description='Z-Probe calibration')
    parser.add_argument('--bed-temp', type=int, default=DEFAULT_BED_TARGET_TEMP, help='Target bed temperature in Celsius')
    parser.add_argument('--disable-bed', action='store_true', help='Disable bed heating after calibration')
    parser.add_argument('--run-g29', action='store_true', help='Run G29 P1 to repopulate build surface mesh data')
    args = parser.parse_args()

    printer = PrinterController(SERIAL_PORT, BAUD_RATE, TIMEOUT)
    printer.run(args.bed_temp, args.disable_bed, args.run_g29)
