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
DEFAULT_DIMENSIONS = [235, 235, 235] # If your printer does not report geometry with M115, set these instead
PROBE_DEPLOY_CMD = "M280 P0 S10"
PROBE_STOW_CMD = "M280 P0 S160"
PROBE_STOW_DELAY = 2.190

class PrinterController:
    def __init__(self, port, baud_rate, timeout):
        self.ser = serial.Serial(port, baud_rate, timeout=timeout)
        self.z_height = SAFE_Z_HEIGHT
        self.trigger_height = 0.0
        self.probe_offsets = {"X": 0.0, "Y": 0.0, "Z": 0.0}
        self.bed_width = None
        self.bed_height = None

    def message(self, msg):
        self.send_command(f"M117 {msg}")

    def send_command(self, command, timeout=5):
        """Send command to the printer and wait for the response."""
        self.ser.reset_input_buffer()
        self.ser.write((command + '\n').encode())
        time.sleep(0.1)
        responses = []
        start_time = time.time()
        print(f"\n{command}:")
        while True:
            if self.ser.in_waiting > 0:
                response = self.ser.readline().decode().strip()
                responses.append(response)
                print(f"\t{response}")
                if response.startswith("ok"):
                    break
            if time.time() - start_time > timeout:
                break
        return '\n'.join(responses)

    def get_printer_information(self):
        bed_response = self.send_command("M115")
        for line in bed_response.split('\n'):
            if "area:{full:{min:" in line:
                dimensions = line.split('max:{')[1].split('}')[0].split(',')
                for dimension in dimensions:
                    if 'x:' in dimension:
                        self.bed_width = float(dimension.split(':')[1])
                    if 'y:' in dimension:
                        self.bed_height = float(dimension.split(':')[1])
                break
        if self.bed_width is None or self.bed_height is None:
            self.bed_width = DEFAULT_DIMENSIONS[0]
            self.bed_height = DEFAULT_DIMENSIONS[1]
        probe_response = self.send_command("M851")
        for line in probe_response.split('\n'):
            if line.startswith("M851"):
                parts = line.split()
                for part in parts:
                    if part.startswith("X"):
                        self.probe_offsets["X"] = float(part[1:])
                    elif part.startswith("Y"):
                        self.probe_offsets["Y"] = float(part[1:])
                    elif part.startswith("Z"):
                        self.probe_offsets["Z"] = float(part[1:])
                break

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
    
    def calculate_center_position(self):
        """Calculates the center position of the bed considering probe offsets."""
        center_x = (self.bed_width / 2) - self.probe_offsets["X"]
        center_y = (self.bed_height / 2) - self.probe_offsets["Y"]
        return center_x, center_y

    def wait_for_temperature(self, target_temp):
        while True:
            response = self.send_command("M105")  # Request temperature
            if response.startswith("ok T:"):
                current_temp = float(response.split(":")[2].split()[0])
                if current_temp >= target_temp:
                    break
            time.sleep(1)

    def coarse_probe(self):
        self.message("Coarse range check...")
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
        self.message(f"Z height: {self.z_height}")

    def fine_probe(self):
        z_heights = []
        for run in range(3):
            self.message(f"Fine range check (run {run + 1}/3)...")
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
            z_heights.append(self.z_height)
            self.message(f"Z height: {self.z_height}")
            self.send_command(PROBE_STOW_CMD)
            time.sleep(PROBE_STOW_DELAY)            
        final_z_height = sum(z_heights) / len(z_heights)
        return final_z_height

    def run(self, bed_temp_target, disable_bed, run_g29, skip_homing):
        try:
            self.message("Calibrating Z-offset...")

            self.get_printer_information()

            center_x, center_y = self.calculate_center_position()
            print(f"Center: {center_x}, {center_y}")

            self.send_command("M420 S0 Z0")
            
            if not skip_homing:
                self.send_command("G28")
                time.sleep(10)

            time.sleep(10)
            self.send_command(f"M140 S{bed_temp_target}")
            self.message("Heating bed...")
            self.wait_for_temperature(bed_temp_target)
            time.sleep(1)

            self.send_command("G90")
            self.send_command(f"G0 F500 Z{SAFE_Z_HEIGHT}")
            time.sleep(1)

            self.send_command(f"G0 F5000 X{center_x} Y{center_y}")
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
                    print((["X", "Y"][r]))
                    time.sleep(1)

            time.sleep(1)
            self.send_command("M500")

            time.sleep(3)
            self.message(f"Z-offset Set to: -{final_z_height}")
            time.sleep(3)

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
    parser.add_argument('--skip-homing', action='store_true', help='Skip homing (G28) before calibration')
    args = parser.parse_args()

    printer = PrinterController(SERIAL_PORT, BAUD_RATE, TIMEOUT)
    printer.run(args.bed_temp, args.disable_bed, args.run_g29, args.skip_homing)
