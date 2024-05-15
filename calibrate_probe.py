import serial
import time
import sys

# Connect to the serial port of your 3D printer
SERIAL_PORT = '/dev/ttyACM0'  # Change to your actual serial port
BAUD_RATE = 115200

def message(msg):
    send_command(ser, f"M117 {msg}")
    print(msg)

def send_command(ser, command, timeout=5):
    ser.reset_input_buffer()
    ser.write((command + '\n').encode())
    time.sleep(0.1)
    responses = []
    start_time = time.time()
    while True:
        if ser.in_waiting > 0:
            response = ser.readline().decode().strip()
            responses.append(response)
            if response.startswith("ok"):
                break
        if time.time() - start_time > timeout:
            break
    print(command + ":")
    print(responses)
    return '\n'.join(responses)

def get_probe_status(ser):
    response = send_command(ser, "M119")
    probe_status_lines = [line for line in response.split('\n') if "z_probe:" in line]
    if probe_status_lines:
        probe_status = probe_status_lines[0].split(":")[1].strip()
        if probe_status.lower() == "open":
            print("open")
            return "OPEN"
        elif probe_status.lower() == "triggered":
            print("triggered")
            return "TRIGGERED"
    return None

def probe_triggered(ser):
    probe_status = get_probe_status(ser)
    return probe_status == "TRIGGERED"

def wait_for_response(ser, expected_substring):
    while True:
        response = ser.readline().decode().strip()
        if expected_substring in response:
            return True
        if response.startswith("Error"):
            return False

def wait_for_temperature(ser, target_temp):
    while True:
        response = send_command(ser, "M105")  # Request temperature
        if response.startswith("ok T:"):
            current_temp = float(response.split(":")[2].split()[0])
            if current_temp >= target_temp:
                break
        time.sleep(1)

with serial.Serial(SERIAL_PORT, BAUD_RATE, timeout=10) as ser:
    z_height = 0.0
    triggered = False
    try:
        message("Starting Z-Probe calibration...")

        # Disable bed leveling and reset saved mesh
        send_command(ser, "M420 S0 Z0")

        # Home all axes
        send_command(ser, "G28")
        time.sleep(10)

        # Start heating the bed
        send_command(ser, "M140 S65")
        message("Heating bed...")

        # Wait for bed to reach target temperature
        wait_for_temperature(ser, 50)

        # Go to the center of the bed
        send_command(ser, "G90")
        send_command(ser, "G0 F500 Z7")
        time.sleep(1)

        send_command(ser, "G0 F5000 X156.3 Y124.4")
        time.sleep(3)

        # Deploy probe
        send_command(ser, "M280 P0 S10")

        # Relative positioning
        send_command(ser, "G91")

        # Initial coarse probe
        z_height = 7.0
        coarse_step = 0.2
        trigger_height = 0.0

        message("Starting coarse range check...")

        while not triggered and z_height > 0:
            if probe_triggered(ser):
                message("Probe triggered!")

                triggered = True
                response = send_command(ser, "M114")  # Request current position

                # Parse current Z position from M114 response
                current_z_position = float(response.split('Z:')[1].split()[0])
                trigger_height = current_z_position
                break
            else:
                response = send_command(ser, f"G0 Z-{coarse_step}")  # Lower by coarse_step
                z_height -= coarse_step
                print(z_height)

        message(f"Finished. Current Z height: {z_height}")
        time.sleep(3)

        # Release alarm
        send_command(ser, "M280 P0 S160")
        time.sleep(2.190)

        # Move back to safe distance
        send_command(ser, "G90") # Absolute positioning
        send_command(ser, "G0 F500 Z7")
        time.sleep(3)
        
        z_height = trigger_height + 0.2  # Start 0.2 mm higher than the triggered position
        triggered = False

        # Deploy probe
        send_command(ser, "M280 P0 S10")
        time.sleep(0.650)

        send_command(ser, f"G0 Z{z_height}")
        
        # Relative positioning
        send_command(ser, "G91")

        message("Starting fine range check...")

        # Fine probe
        z_heights = []
        for run in range(3):
            triggered = False
            z_height = trigger_height + 0.2  # Start 0.2 mm higher than the triggered position

            # Deploy probe
            send_command(ser, "M280 P0 S10")
            time.sleep(0.650)
            
            send_command(ser, "G90") # Absolute positioning
            send_command(ser, f"G0 Z{z_height}")

            # Relative positioning
            send_command(ser, "G91")

            message(f"Starting fine range check (run {run + 1}/3)...")

            while not triggered and z_height > 0:
                if probe_triggered(ser):
                    triggered = True
                    break
                else:
                    response = send_command(ser, "G1 Z-0.01 F50")  # Lower by 0.01
                    z_height -= 0.01
                    print(z_height)

            z_heights.append(-z_height)

            # Release alarm and stow probe
            send_command(ser, "M280 P0 S160")
            time.sleep(2.190)

            send_command(ser, "G0 F500 Z7")
            time.sleep(3)

        final_z_height = sum(z_heights) / len(z_heights)
        message(f"Finished. Final Z-Probe Offset: {final_z_height}")
        time.sleep(3)

        send_command(ser, f"M851 Z{final_z_height}")
        message(f"Z-Probe offset set to: {final_z_height}")
        
        # Turn off bed heater
        send_command(ser, "M140 S0")
        time.sleep(1)

        # Save configuration
        send_command(ser, "M500")
        time.sleep(5)

    except serial.SerialException as e:
        print(f"Serial communication error: {e}")
    except Exception as e:
        print(f"Error occurred: {e}")
    finally:
        ser.close()
        sys.exit()