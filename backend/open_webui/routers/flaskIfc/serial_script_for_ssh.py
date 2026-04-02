import serial
import sys
import time
import portalocker
import paramiko
import re

DEFAULT_COMMAND_TIMEOUT = 7200
SHELL_PROMPT_REGEX = re.compile(r"root@[\w\-]+:[\w\/\-]+#")
TSISIM_SHELL_PROMPT_REGEX = re.compile(r"root@[\w\-]+:[\w\/\-]+~")
SERIAL_LOCK_FILE = "./serial_port.lock"  # Use a lock file

LINUX_LOGGED_IN_PROMPT = "@agilex7_dk_si_agf014ea"
LINUX_LOGIN_PROMPT = "agilex7_dk_si_agf014ea"
QEMU_LOGIN_PROMPT = "qemuarm64"
QEMU_LOGGED_IN_PROMPT = "@qemuarm64"
QEMU_TSISIM_LOGIN_PROMPT = "tssim"
QEMU_TSISIM_LOGGED_IN_PROMPT = "@tsisim"
SYSTEMD_LOGGED_IN_PROMPT = "@agilex7dksiagf014ea"
SYSTEMD_LOGIN_PROMPT = "agilex7dksiagf014ea"
LINUXB_LOGGED_IN_PROMPT = "@agilex7_dk_si_agf014eb"
LINUXB_LOGIN_PROMPT = "agilex7_dk_si_agf014eb"
SYSTEMDB_LOGGED_IN_PROMPT = "@agilex7dksiagf014eb"
SYSTEMDB_LOGIN_PROMPT = "agilex7dksiagf014eb"


hostname = "localhost"
username = "root"
password = "taos#123"  # use password based auth
port = 2222


def is_lock_available():
    try:
        with open(SERIAL_LOCK_FILE, "w") as lock_fp:
            portalocker.lock(lock_fp, portalocker.LOCK_EX | portalocker.LOCK_NB)
            portalocker.unlock(lock_fp)
        return True  # Lock was successfully acquired
    except portalocker.exceptions.LockException:
        return False  # Lock is already held by another process


def check_for_specific_prompt(shell, timeout=10, prompt=LINUX_LOGGED_IN_PROMPT):
    data = "\0"
    start = time.time()

    while time.time() - start < timeout:
        try:
            line = b""
            while time.time() - start < timeout:
                byte = shell.recv(1)  # Read one byte at a time
                line += byte
                if byte in [b"\n", b"#", b">"]:  # Stop when delimiter is found
                    break

            if line:
                try:
                    read_next_line = line.decode("utf-8", errors="replace")
                except UnicodeDecodeError as e:
                    print("Decoding error:", e, "Raw line:", line)
                    continue

                if (
                    prompt in read_next_line.strip()
                    or QEMU_LOGGED_IN_PROMPT in read_next_line.strip()
                    or QEMU_TSISIM_LOGGED_IN_PROMPT in read_next_line.strip()
                    or SYSTEMD_LOGGED_IN_PROMPT in read_next_line.strip()
                    or LINUXB_LOGGED_IN_PROMPT in read_next_line.strip()
                    or SYSTEMDB_LOGGED_IN_PROMPT in read_next_line.strip()
                ):
                    return True
            else:
                return False

        except Exception as e:
            print(f"Shell read error: {e}")
            return False
        except KeyboardInterrupt:
            return False

    return False


def check_for_prompt(shell, timeout=10):
    data = "\0"
    first_time = True
    start = time.time()

    while time.time() - start < timeout:
        try:
            line = b""
            while time.time() - start < timeout:
                byte = shell.recv(1)  # Read one byte at a time
                line += byte
                if byte in [b"\n", b"#", b">"]:  # Stop when delimiter is found
                    break

            if line:
                try:
                    read_next_line = line.decode("utf-8", errors="replace").strip()
                except UnicodeDecodeError as e:
                    print("Decoding error:", e, "Raw line:", line)
                    continue

                if (
                    "run-platform-done" in read_next_line
                    or "SOCFPGA_AGILEX7 " in read_next_line
                    or "Unknown command " in read_next_line
                    or LINUX_LOGGED_IN_PROMPT in read_next_line
                    or QEMU_LOGGED_IN_PROMPT in read_next_line
                    or QEMU_TSISIM_LOGGED_IN_PROMPT in read_next_line
                    or SYSTEMD_LOGGED_IN_PROMPT in read_next_line
                    or LINUXB_LOGGED_IN_PROMPT in read_next_line
                    or SYSTEMDB_LOGGED_IN_PROMPT in read_next_line
                    or "imx8mpevk" in read_next_line
                ):
                    return True

                if "(Yocto Project Reference Distro) 5.2." in read_next_line and (
                    LINUX_LOGIN_PROMPT in read_next_line
                    or QEMU_LOGGED_IN_PROMPT in read_next_line
                    or QEMU_TSISIM_LOGGED_IN_PROMPT in read_next_line
                    or SYSTEMD_LOGIN_PROMPT in read_next_line
                    or LINUXB_LOGIN_PROMPT in read_next_line
                    or SYSTEMDB_LOGIN_PROMPT in read_next_line
                ):
                    time.sleep(3)
                    shell.send("root\n")
                    return True

                if first_time:
                    first_time = False
                else:
                    if "read in progress" not in read_next_line:
                        data += read_next_line + "\n"
            else:
                break

        except Exception as e:
            print(f"Shell read error: {e}")
            return False
        except KeyboardInterrupt:
            return False

    return False


def tsi_apc_manager_service_restart(shell):
    shell.send(f"systemctl restart tsi-apc-manager\n")
    if not check_for_specific_prompt(shell, timeout=3, prompt=LINUX_LOGGED_IN_PROMPT):
        return None


def clean_up_after_abort(shell):
    print("Sending Ctrl-C to abort current task...")
    shell.send("\x03")  # Ctrl-C
    shell.send("\x03")

    if not check_for_prompt(shell, 10):
        if not check_for_specific_prompt(
            shell, timeout=3, prompt=LINUX_LOGGED_IN_PROMPT
        ):
            print(
                "Error: Linux prompt not detected, likely job is stuck or not running"
            )
            return False
        else:
            tsi_apc_manager_service_restart(shell)
            if not check_for_prompt(shell, 3):
                print(
                    "Warning: systemctl restart tsi-apc-manager did not respond to 'restart'."
                )
                return False
    else:
        tsi_apc_manager_service_restart(shell)
        if not check_for_prompt(shell, 3):
            print(
                "Warning: systemctl restart tsi-acp-manager did not respond to 'restart'."
            )
            return False

    print("tsi-apc-manager restart successful.")
    return True


def abort_serial_portion(shell):
    while not is_lock_available():
        time.sleep(1)

    with open(SERIAL_LOCK_FILE, "w") as lock_fp:
        portalocker.lock(lock_fp, portalocker.LOCK_EX)
        try:
            # shell.reset_output_buffer()
            # shell.reset_input_buffer()

            shell.send("\x03")  # Ctrl-C
            clean_up_after_abort(shell)

        finally:
            portalocker.unlock(lock_fp)


def initiate_serial_download(shell, filename):
    while not is_lock_available():
        time.sleep(1)

    with open(SERIAL_LOCK_FILE, "w") as lock_fp:
        portalocker.lock(lock_fp, portalocker.LOCK_EX)
        try:
            # shell.reset_output_buffer()
            # shell.reset_input_buffer()

            shell.send("\x03")  # Ctrl-C
            clean_up_after_abort(shell)

        finally:
            portalocker.unlock(lock_fp)


def explicit_boot_command(shell):
    if not is_lock_available():
        return None

    time.sleep(2)
    shell.send("boot\n")


def explicit_root_command(shell, path):
    if not is_lock_available():
        return None

    timeout = 180  # seconds
    start_time = time.time()

    while time.time() - start_time < timeout:
        if not is_lock_available():
            return None

        line = shell.recv(1024).decode("utf-8", errors="replace").strip()
        print("SERIAL/TARGET:", line)

        if line:
            if (
                "(Yocto Project Reference Distro) 5.2." in line
                and LINUX_LOGIN_PROMPT in line
            ) or (QEMU_LOGIN_PROMPT in line) or (QEMU_TSISIM_LOGIN_PROMPT in line):
                time.sleep(3)
                shell.send("root\n")
                break


def restart_txe_serial_portion(shell, path):
    shell.send(path + "\n")
    time.sleep(6)

def send_shell_command(shell, command, timeout=DEFAULT_COMMAND_TIMEOUT):
    if not is_lock_available():
        return None
    try:
        shell.send(command + "\n")
        data = "\0"
        command_seen = False
        start = time.time()

        while time.time() - start < timeout:
            try:
                line = b""
                while time.time() - start < timeout:
                    if not is_lock_available():
                        return data

                    byte = shell.recv(1)
                    line += byte

                    # Check for early exit condition
                    if b"File receive completed" in line:
                        return data

                    if byte in [b"\n", b"#"]:
                        break
                line = line.decode("utf-8", errors="replace")
                if line:
                    try:
                        read_next_line = line.strip()
                    except UnicodeDecodeError as e:
                        print("Decoding error:", e, "Raw line:", line)
                        continue

                    # New code to look for command instead of prompt
                    if ( command in line ) and command_seen is False :
                        command_seen = True;
                        continue

                    # Wait for the command to be echoed before looking for prompt
                    if (command_seen is False):
                        continue

                    # Check for known completion keywords
                    if any(
                        keyword in read_next_line
                        for keyword in [
                            "run-platform-done",
                            "SOCFPGA_AGILEX7 ",
                            "Unknown command ",
                            LINUX_LOGGED_IN_PROMPT,
                            LINUXB_LOGGED_IN_PROMPT,
                            SYSTEMD_LOGGED_IN_PROMPT,
                            SYSTEMDB_LOGGED_IN_PROMPT,
                            QEMU_LOGGED_IN_PROMPT,
                            QEMU_TSISIM_LOGGED_IN_PROMPT,
                            "imx8mpevk",
                        ]
                    ):
                        break

                    # Check for shell prompt to exit
                    if SHELL_PROMPT_REGEX.search(read_next_line) or TSISIM_SHELL_PROMPT_REGEX.search(read_next_line):
                        break
                    # Filter out noisy lines
                    if not any(
                        keyword in read_next_line
                        for keyword in ["read in progress", "tSavorite"]
                    ):
                        data += read_next_line + "\n"
                else:
                    break

            except Exception as e:
                return f"Error reading from shell: {e}"
            except KeyboardInterrupt:
                return "Program interrupted by user"

        lines = data.splitlines()
        if lines and command.lower() in lines[0].lower():
            data = "\n".join(lines[1:])
        return data

    except Exception as e:
        return f"Error: {e}"


def pre_and_post_check(shell):
    if is_lock_available() != True:
        return None

    flag = ["ok"]

    shell.send("\n")
    time.sleep(0.1)
    shell.send("\n")

    while True:
        line = b""
        while True:
            if is_lock_available() != True:
                return line
            try:
                byte = shell.recv(1)  # Read one byte at a time
                if byte in [b"\n", b"#"]:  # Stop when delimiter is found
                    break
                line += byte
            except Exception as e:
                return f"Error reading from shell: {e}"
            except KeyboardInterrupt:
                return "Program interrupted by user"

        decoded_line = line.decode("utf-8", errors="replace")
        if (
            "agilex7_dk_si_agf014ea login:" in decoded_line
            or "qemuarm64 login:" in decoded_line
            or "tsisim login:" in decoded_line
            or "agilex7dksiagf014ea login:" in decoded_line
            or "agilex7_dk_si_agf014eb login:" in decoded_line
            or "agilex7dksiagf014eb login:" in decoded_line
        ):
            time.sleep(0.1)
            flag[0] = "root issue"
            print("root issue")
            break
        elif "SOCFPGA_AGILEX7" in decoded_line:
            time.sleep(0.1)
            flag[0] = "boot issue"
            print("boot issue")
            break
        elif (
            "@agilex7_dk_si_agf014ea:" in decoded_line
            or "qemuarm64:" in decoded_line
            or "tsisim:" in decoded_line
            or "agilex7dksiagf014ea:" in decoded_line
            or "agilex7_dk_si_agf014eb:" in decoded_line
            or "agilex7dksiagf014eb:" in decoded_line
        ):
            time.sleep(0.1)
            break

    if flag[0] == "root issue":
        shell.send("root\n")
        check_for_prompt(shell, 3)
    elif flag[0] == "boot issue":
        explicit_boot_command(shell)

def connect_to_shell():
    try:
        # Create SSH client
        ssh = paramiko.SSHClient()
        ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())

        # Establish a transport and attempt 'none' authentication
        transport = paramiko.Transport((hostname, port))
        transport.connect(username=username, password=password)

        # Attach the transport to the client
        ssh._transport = transport

        # Open a shell session
        shell = ssh.invoke_shell()

        if shell is None:
            print("No connection establisted with shell")

        # Wait and read response
        time.sleep(2)  # wait for command to execute
        output = shell.recv(1024).decode()
        print("Response:", output)
    except Exception as e:
        print("SSH connection failed:", e)
    finally:
        return ssh, shell


def disconnect_shell(ssh, shell):
    try:
        # Close connection
        shell.close()
        ssh.close()
    except Exception as e:
        print("SSH disconnection failed:", e)


# This script can be run in standalone as well
if __name__ == "__main__":
    ssh, shell = connect_to_shell()
    if len(sys.argv) == 2 and sys.argv[1] == "abort":
        abort_serial_portion(shell)
    if len(sys.argv) == 3 and sys.argv[1] == "restart":
        path = sys.argv[2]
        restart_txe_serial_portion(shell, path)
    else:
        response = send_shell_command(shell, sys.argv[1])
        print(response)
    if len(sys.argv) > 3:
        print("Usage: python script.py <command>")
    if ssh != None and shell != None:
        disconnect_shell(ssh, shell)
    sys.exit(1)
