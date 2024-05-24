import serial
import time
import sys

# Constants
SERIAL_PORT = '/dev/ttyACM0'  # Change to your actual serial port
BAUD_RATE = 115200
TIMEOUT = 10

class PrinterController:
    def __init__(self, port, baud_rate, timeout):
        self.ser = serial.Serial(port, baud_rate, timeout=timeout)

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

    def run(self):
        try:
            while True:
                command = input("Enter a command (or 'exit' to quit): ")
                if command.lower() == 'exit':
                    break
                self.send_command(command)
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