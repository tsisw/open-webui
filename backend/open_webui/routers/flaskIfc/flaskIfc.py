from urllib.parse import quote as url_quotie
from flask import Flask, render_template, request, jsonify, make_response
import subprocess
import threading
import json
import time
import os
import shlex
import subprocess
import mmap
import signal
import serial
import serial_script
import serial_script_for_ssh
import re
import inspect
import pathlib
import psutil
from werkzeug.datastructures import FileStorage
from werkzeug.utils import secure_filename

job_status = {"running": False, "result": "", "thread": None, "current_job": None}

app = Flask(__name__)

port = "/dev/ttyUSB3"
# port = '/dev/ttyUSB2'
baudrate = "921600"
# baudrate = '115200'
exe_path = "/usr/bin/tsi/bin/"

DEFAULT_MODEL = "TinyLlama:latest"
DEFAULT_BACKEND = "tSavorite"
DEFAULT_TOKEN = 20  # This matches what we have on Open-WebUI
DEFAULT_REPEAT_PENALTY = 1.1
DEFAULT_BATCH_SIZE = 512
DEFAULT_TOP_K = 4  # This matches what we have on Open-WebUI
DEFAULT_TOP_P = 0.9
DEFAULT_LAST_N = 64
DEFAULT_CONTEXT_LENGTH = 2048
DEFAULT_TEMP = 0.8

DEFAULT_MODEL_COMMAND_RUN_TIMEOUT = 14400
DEFAULT_TIMEOUT = 300
DEFAULT_THREAD_TIMEOUT = 900
PER_1G_TIMEOUT_SECS = 240
GB = 1024 * 1024 * 1024

parameters = {
    "aottests": "no",
    "target": "opu",
    "num_predict": DEFAULT_TOKEN,
    "repeat_penalty": DEFAULT_REPEAT_PENALTY,
    "num_batch": DEFAULT_BATCH_SIZE,
    "top_k": DEFAULT_TOP_K,
    "top_p": DEFAULT_TOP_P,
    "repeat_last_n": DEFAULT_LAST_N,
    "num_ctx": DEFAULT_CONTEXT_LENGTH,
    "temperature": DEFAULT_TEMP,
}

import os
import socket

shell = None
ssh = None
initialization_done = False


def initialize_shell():
    global ssh, shell, initialization_done
    # Step 1: Get the hostname
    tsi_hostname = socket.gethostname()
    os.environ["TSI_HOSTNAME"] = tsi_hostname

    # Step 3: Set environment variables based on hostname
    fpga_hosts = [
        "fpga1.tsavoritesi.net",
        "fpga2.tsavoritesi.net",
        "fpga3.tsavoritesi.net",
        "fpga4.tsavoritesi.net",
    ]

    if tsi_hostname not in fpga_hosts:
        ssh, shell = serial_script_for_ssh.connect_to_shell()
    initialization_done = True


def close_shell(ssh, shell):
    if ssh != None and shell != None:
        serial_script_for_ssh.disconnect_shell(ssh, shell)


def pre_and_post_check():
    if shell is None:
        serial_script.pre_and_post_check(port, baudrate)
    else:
        serial_script_for_ssh.pre_and_post_check(shell)


def send_serial_command(command, timeout=DEFAULT_TIMEOUT, region="USA"):
    if shell is None:
        return serial_script.send_serial_command(
            port, baudrate, command, timeout, region
        )
    else:
        return serial_script_for_ssh.send_shell_command(shell, command, timeout)


def restart_txe_serial_portion(command_path):
    if shell is None:
        return serial_script.restart_txe_serial_portion(port, baudrate, command_path)
    else:
        return serial_script_for_ssh.restart_txe_serial_portion(shell, command_path)


def abort_serial_portion():
    if shell is None:
        return serial_script.abort_serial_portion(port, baudrate)
    else:
        return serial_script_for_ssh.abort_serial_portion(shell)


def initiate_serial_download_command(filename):
    if shell is None:
        return serial_script.initiate_serial_download(port, baudrate, filename)
    else:
        return serial_script_for_ssh.initiate_serial_download(shell, filename)


def is_job_running():
    if job_status["running"] == True:
        return True
    return False


@app.route("/")
def index():

    pre_and_post_check()

    return render_template("index.html")


@app.route("/llama-cli", methods=["GET"])
def llama_cli_serial_command():

    pre_and_post_check()

    # ./run_llama_cli.sh "my cat's name" "10" "tinyllama-vo-5m-para.gguf" "none"
    model = request.args.get("model")
    backend = request.args.get("backend")
    tokens = request.args.get("tokens")
    prompt = request.args.get("prompt")
    repeat_penalty = request.args.get("repeat-penalty", DEFAULT_REPEAT_PENALTY)
    batch_size = request.args.get("batch-size", DEFAULT_BATCH_SIZE)
    top_k = request.args.get("top-k", DEFAULT_TOP_K)
    top_p = request.args.get("top-p", DEFAULT_TOP_P)
    last_n = request.args.get("last-n", DEFAULT_LAST_N)
    context_length = request.args.get("context-length", DEFAULT_CONTEXT_LENGTH)
    temp = request.args.get("temp", DEFAULT_TEMP)

    # Define the model path (update with actual paths)
    model_paths = {
        "tiny-llama": "tinyllama-vo-5m-para.gguf",
        "Tiny-llama-F32": "Tiny-Llama-v0.3-FP32-1.1B-F32.gguf",
    }

    model_path = model_paths.get(model, "")
    if not model_path:
        model_path = model
    # Build llama-cli command
    # command = [
    #    "./llama-cli",
    #    "-p", prompt,
    #    "-m", model_path,
    #    "--device", backend,
    #    "--temp", "0",
    #    "--n-predict", tokens,
    #    "--repeat-penalty", "1",
    #    "--top-k", "0",
    #    "--top-p", "1"
    # ]
    # URL to Test this end point is as follows
    # http://10.50.30.167:5001/llama-cli?model=tiny-llama&backend=tSavorite&tokens=5&prompt=Hello+How+are+you
    script_path = "./run_llama_cli.sh"
    command = f'cd {exe_path}; {script_path} "{prompt}" {tokens} {model_path} {backend} {repeat_penalty} {batch_size} {top_k} {top_p} {last_n} {context_length} {temp}'
    try:
        job_status["running"] = True
        job_status["current_job"] = inspect.currentframe().f_code.co_name
        result = send_serial_command(command)
        job_status["running"] = False
        return result, 200
    except subprocess.CalledProcessError as e:
        return f"Error executing script: {e.stderr}", 500


UPLOAD_FOLDER = "./"  # Directory where recvFromHost is loaded
destn_path = "/tsi/proj/model-cache/gguf/"  # Destination Directory in FPGA where uploaded files will be stored
safetensor_destn_path = "/tsi/proj/model-cache/safetensors/"  # Destination Directory in FPGA where uploaded files will be stored
tokenizer_destn_path = "/tsi/proj/model-cache/tokenizer/"  # Destination Directory in FPGA where uploaded files will be stored
file_transfer_path = (
    "/proj/rel/fpga/tsi/file-transfer"  # The copy to FPGA files are in this path
)
pytorch_model_path = "../../../../../tsi-customer/build-fpga/archives/"  # This is tsi-customer folder relative to open-webui
tsi_customer_path = (
    "../../../../../tsi-customer"  # This is relative to tsi-customer folder
)
aottests_model_path = "/usr/bin/tsi/bin/aot-tests/models/"
app.config["UPLOAD_FOLDER"] = UPLOAD_FOLDER
os.makedirs(
    UPLOAD_FOLDER, exist_ok=True
)  # Create the upload folder if it doesn't exist


def read_cmd_from_serial(port, baudrate, command):
    job_status["running"] = True
    job_status["current_job"] = inspect.currentframe().f_code.co_name
    temp = send_serial_command(command, timeout=300)
    print(temp)
    job_status["running"] = False


@app.route("/delete-file", methods=["POST", "GET"])
def delete_file():

    pre_and_post_check()

    if request.method == "POST":

        d_path = request.form.get("deletion_file_path")
        filename = request.form.get("file_name")
        command = f"cd {d_path}; rm {filename}"
        read_cmd_from_serial(port, baudrate, command)
        return "Done"
    return render_template("delete.html")


@app.route("/upload-gguf", methods=["POST", "GET"])
def upload_serial_command():

    pre_and_post_check()

    if request.method == "POST":
        # Check if a file was submitted
        if "file" not in request.files:
            return "No file part"
        file = request.files["file"]

        # Check if the file is empty
        if file.filename == "":
            return "No file selected"

        # Save the file if it exists
        if file:
            filename = file.filename  # secure_filename(file.filename)
            process = subprocess.Popen(["./copy2fpga-x86.sh", filename], text=True)
            copy2fpgax86prints = "Starting copy2fpga-x86 and sending file..."
            print(copy2fpgax86prints)
            file.save(os.path.join(app.config["UPLOAD_FOLDER"], filename))
            time.sleep(3)
            script_path = "./recvFromHost "
            command = f"cd {exe_path}; {script_path} {destn_path}{filename}"

            def scriptRecvFromHost():
                try:
                    result = send_serial_command(command)
                    job_status["result"] = result
                    print(result)
                    recv_output = result
                except subprocess.CalledProcessError as e:
                    job_status["result"] = f"Error: {e.stderr}"
                finally:
                    job_status["running"] = False

            thread = threading.Thread(target=scriptRecvFromHost)
            job_status = {"running": True, "result": "", "thread": thread}
            thread.start()
            thread.join()
            stdout, stderr = process.communicate()

        read_cmd_from_serial(port, baudrate, f"cd {destn_path}; ls -lt")

        return render_template(
            "uploadtofpga.html",
            apple=process,
            recvoutput=f"On FPGA Target, recvFromHost completed ; transfered file:{filename} received",
        )
    return render_template("upload.html")  # Display the upload form


def ensure_remote_dir(sftp, remote_path):
    """
    Recursively create remote directories if they don't exist.
    """
    dirs = remote_path.strip("/").split("/")
    current_dir = ""
    for dir_part in dirs:
        current_dir += "/" + dir_part
        try:
            sftp.stat(current_dir)
        except IOError:
            print(f"Creating remote directory: {current_dir}")
            sftp.mkdir(current_dir)


def actual_transfer(remote_dir, file, file_size):
    # Check if the file is empty
    if file.name == "":
        return "No file selected"

    if ssh != None and shell != None:
        if file:
            filename = os.path.basename(file.name)  # secure_filename(file.filename)
            # Create Sftp client and transfer file
            sftp = ssh.open_sftp()

            remote_path = os.path.join(remote_dir, filename)
            if not os.path.exists(remote_dir):
                os.makedirs(remote_dir)

            # Ensure remote directory exists
            ensure_remote_dir(sftp, remote_dir)
            try:
                sftp.put(file.name, remote_path)
            except Exception as e:
                return f"File-transfer failed: {e}", 500
            sftp.close()
            return f"File transfer succeeded", 200
    # Save the file if it exists
    if file:
        filename = os.path.basename(file.name)  # secure_filename(file.filename)
        script_path = os.path.join(file_transfer_path, "copy2fpga-setup.sh")
        try:
            process = subprocess.Popen(
                [script_path], text=True
            )  # subprocess.run(["{file_transfer_path}/copy2fpga-setup.sh"], text=True, capture_output=True)
            print("process created")
        except Exception as e:
            print("process creation failed for copy2fpga-setup.sh")
            return f"File-transfer setup failed: {e}", 500
        stdout, stderr = process.communicate()
        script_path = "./recvFromHost "
        command = f"cd {exe_path}; {script_path} {remote_dir}{filename}\n"

        timeout = max(
            PER_1G_TIMEOUT_SECS * file_size / GB, DEFAULT_THREAD_TIMEOUT
        )  # 4 mins per 1 GB is the speed we observe

        print("Command:", command, "Timeout:", timeout)

        def scriptRecvFromHost():
            try:
                result = send_serial_command(command, timeout=timeout)
                job_status["result"] = result
                print("Success:", job_status["result"])
                recv_output = result
            except subprocess.CalledProcessError as e:
                job_status["result"] = f"Error: {e.stderr}"
                print("Err:", job_status["result"])
            finally:
                print("Thread Complete:", job_status["result"])
                job_status["running"] = False

        thread = threading.Thread(target=scriptRecvFromHost)
        job_status = {"running": True, "result": "", "thread": thread}

        try:
            script_path = os.path.join(file_transfer_path, "copy2fpga-x86.sh")
            full_path = os.path.abspath(file.name)
            process = subprocess.Popen([script_path, full_path], text=True)
            print("process completed")
        except Exception as e:
            print("process completed with exception")
            return f"copy2fpga-x86.sh failed: {e}", 500

        print("Thread starting")
        thread.start()
        print("Thread started")

        start = time.time()
        while (time.time() - start < timeout) and (job_status["running"] != False):
            time.sleep(1)
        if time.time() - start < timeout:
            print("Thread exited normally", job_status["running"])
        else:
            print("Thread timed out", job_status["running"])


def normalize_model_name(model_name):
    if ":" not in model_name:
        return model_name + ":latest"
    return model_name


@app.route("/api/receive-upload", methods=["GET", "POST"])
def receive_upload_model():

    data = request.get_json()
    incoming_headers = dict(request.headers)
    if is_job_running() == True:
        return (
            manual_response(
                content=f"Server is busy. Current job: {job_status.get('current_job', 'Unknown')}. Please try again later.",
                thinking=None,
                profile_data=None,
                incoming_headers=incoming_headers,
            ),
            503,
        )

    job_status["running"] = True
    job_status["current_job"] = inspect.currentframe().f_code.co_name

    remote_dir = destn_path
    if not os.path.exists(remote_dir):
        os.makedirs(remote_dir)

    file_name = os.path.basename(data["actual_name"])

    filename_without_ext = os.path.splitext(os.path.basename(data["actual_name"]))[0]

    new_file_name = normalize_model_name(data["human_name"])

    print(
        "human_name:",
        data["human_name"],
        "actual_name",
        data["actual_name"],
        "new_file_name:",
        new_file_name,
    )

    preliminary_target_check = send_serial_command(
        f"cd {destn_path}; md5sum {new_file_name}"
    )

    try:
        preliminary_host_check = subprocess.run(
            ["md5sum", data["actual_name"]], capture_output=True, text=True, check=True
        )
    except Exception as e:
        job_status["running"] = False
        return (
            manual_response(
                content=f"File checksum failed: {e}",
                thinking=f"File checksum failed: {e}",
                incoming_headers=incoming_headers,
            ),
            500,
        )

    print("PRELIMINARY TARGET CHECK-SUM: ", preliminary_target_check)
    print("PRELIMINARY HOST/SHELL CHECK-SUM: ", preliminary_host_check.stdout)

    if preliminary_target_check.split()[0].replace(
        "\x00", ""
    ) == preliminary_host_check.stdout.split()[0].replace("\x00", ""):
        job_status["running"] = False
        return (
            manual_response(
                content="File Already Exists",
                thinking="File Already Exists",
                incoming_headers=incoming_headers,
            ),
            200,
        )

    send_serial_command(f"cd {destn_path}; rm {new_file_name}", timeout=300)

    try:
        file_size = os.path.getsize(data["actual_name"])
        file_obj = open(data["actual_name"], "rb")
    except Exception as e:
        job_status["running"] = False
        return (
            manual_response(
                content=f"File open failed: {e}",
                thinking=f"File open failed: {e}",
                incoming_headers=incoming_headers,
            ),
            500,
        )

    full_path = file_obj.name
    print(full_path)
    try:
        actual_transfer(remote_dir, file_obj, file_size)
    except Exception as e:
        job_status["running"] = False
        return (
            manual_response(
                content=f"File transfer failed: {e}",
                thinking=f"File transfer failed: {e}",
                incoming_headers=incoming_headers,
            ),
            500,
        )

    send_serial_command(f"cd {destn_path}; mv {file_name} {new_file_name}", timeout=300)

    if ssh:
        job_status["running"] = False
        return (
            manual_response(
                content="File Download Done",
                thinking="File Download Done",
                incoming_headers=incoming_headers,
            ),
            200,
        )

    print("Listing out existing files")
    send_serial_command(f"cd {destn_path}; ls -lt", timeout=300)

    print("Doing checksum of the upload file")
    target_check_sum = send_serial_command(
        f"cd {destn_path}; md5sum {new_file_name}", timeout=300
    )

    print("TARGET CHECK-SUM: ", target_check_sum)
    print("HOST/SHELL CHECK-SUM: ", preliminary_host_check.stdout)
    job_status["running"] = False

    if target_check_sum.split()[0].replace(
        "\x00", ""
    ) != preliminary_host_check.stdout.split()[0].replace("\x00", ""):
        return (
            manual_response(
                content="Failed checksum match",
                thinking="Failed checksum match",
                incoming_headers=incoming_headers,
            ),
            400,
        )

    return (
        manual_response(
            content="File Download Done",
            thinking="File Download Done",
            incoming_headers=incoming_headers,
        ),
        200,
    )


def remove_url_from_directory_path(url):
    if url.startswith("https://"):
        return url.replace("https://", "")
    elif url.startswith("http://"):
        return url.replace("http://", "")
    return url


@app.route("/api/receive", methods=["GET", "POST"])
def receive_pull_model():

    data = request.get_json()
    incoming_headers = dict(request.headers)

    if is_job_running() == True:
        return (
            manual_response(
                content=f"Server is busy. Current job: {job_status.get('current_job', 'Unknown')}. Please try again later.",
                thinking=None,
                profile_data=None,
                incoming_headers=incoming_headers,
            ),
            200,
        )
    job_status["running"] = True
    job_status["current_job"] = inspect.currentframe().f_code.co_name

    remote_dir = destn_path
    if not os.path.exists(remote_dir):
        os.makedirs(remote_dir)
    try:
        test1 = data["human_name"]
        test2 = data["actual_name"]
    except (TypeError, KeyError) as e:
        job_status["running"] = False
        return (
            manual_response(
                content=f"Invalid JSON data: {e}",
                thinking=f"Invalid JSON data: {e}",
                incoming_headers=incoming_headers,
            ),
            400,
        )

    if os.path.exists("/var/snap/ollama/common/models/blobs/"):
        path = "/var/snap/ollama/common/models/blobs/" + data["actual_name"]
    elif os.path.exists("/usr/share/ollama/.ollama/models/blobs/"):
        path = "/usr/share/ollama/.ollama/models/blobs/" + data["actual_name"]
    else:
        job_status["running"] = False
        return (
            manual_response(
                content=f"No valid path",
                thinking=f"No valid path",
                incoming_headers=incoming_headers,
            ),
            500,
        )

    preliminary_target_check = send_serial_command(
        f"cd {destn_path}; md5sum {data['human_name']}"
    )

    try:
        preliminary_host_check = subprocess.run(
            ["md5sum", path], capture_output=True, text=True, check=True
        )
    except Exception as e:
        job_status["running"] = False
        return (
            manual_response(
                content=f"File checksum failed: {e}",
                thinking=f"File checksum failed: {e}",
                incoming_headers=incoming_headers,
            ),
            500,
        )

    print("PRELIMINARY TARGET CHECK-SUM: ", preliminary_target_check)
    print("PRELIMINARY HOST/SHELL CHECK-SUM: ", preliminary_host_check.stdout)

    if preliminary_target_check.split()[0].replace(
        "\x00", ""
    ) == preliminary_host_check.stdout.split()[0].replace("\x00", ""):
        job_status["running"] = False
        return (
            manual_response(
                content="File Already Exists",
                thinking="File Already Exists",
                incoming_headers=incoming_headers,
            ),
            200,
        )

    send_serial_command(f"cd {destn_path}; rm {data['human_name']}", timeout=300)

    try:
        file_size = os.path.getsize(path)
        file_obj = open(path, "rb")
    except Exception as e:
        job_status["running"] = False
        return (
            manual_response(
                content=f"File open failed: {e}",
                thinking=f"File open failed: {e}",
                incoming_headers=incoming_headers,
            ),
            500,
        )

    full_path = file_obj.name
    print(full_path)
    try:
        actual_transfer(remote_dir, file_obj, file_size)
    except Exception as e:
        job_status["running"] = False
        return (
            manual_response(
                content=f"File transfer failed: {e}",
                thinking=f"File transfer failed: {e}",
                incoming_headers=incoming_headers,
            ),
            500,
        )

    dir_path = os.path.dirname(data["human_name"])  # ✅ Python way

    dir_path = remove_url_from_directory_path(dir_path)

    # Create the directory structure on the target device
    send_serial_command(f"cd {destn_path}; mkdir -p {dir_path}", timeout=300)

    filename = os.path.basename(data["human_name"])

    new_file_name = os.path.join(dir_path, filename)
    new_file_name = normalize_model_name(new_file_name)

    print("Renaming file:", data["human_name"], " to new_file_name:", filename)

    send_serial_command(
        f"cd {destn_path}; mv {data['actual_name']} {new_file_name}",
        timeout=300,
    )

    if ssh:
        job_status["running"] = False
        return (
            manual_response(
                content="File Download Done",
                thinking="File Download Done",
                incoming_headers=incoming_headers,
            ),
            200,
        )
    print("Listing out existing files")
    send_serial_command(f"cd {destn_path}; ls -lt", timeout=300)

    print("Doing checksum of the upload file")
    target_check_sum = send_serial_command(
        f"cd {destn_path}; md5sum {new_file_name}", timeout=300
    )

    print("TARGET CHECK-SUM: ", target_check_sum)
    print("HOST/SHELL CHECK-SUM: ", preliminary_host_check.stdout)

    job_status["running"] = False
    if target_check_sum.split()[0].replace(
        "\x00", ""
    ) != preliminary_host_check.stdout.split()[0].replace("\x00", ""):
        return (
            manual_response(
                content="Failed checksum match",
                thinking="Failed checksum match",
                incoming_headers=incoming_headers,
            ),
            400,
        )

    return (
        manual_response(
            content="File Download Done",
            thinking="File Download Done",
            incoming_headers=incoming_headers,
        ),
        200,
    )


def denormalize_model_name(model_name):
    if model_name.endswith(":latest"):
        return model_name.split(":")[0]
    return model_name


@app.route("/api/opu-delete-model", methods=["GET", "POST"])
def opu_delete_model():
    data = request.get_json()

    incoming_headers = dict(request.headers)
    if is_job_running() == True:
        return (
            manual_response(
                content=f"Server is busy. Current job: {job_status.get('current_job', 'Unknown')}. Please try again later.",
                thinking=None,
                profile_data=None,
                incoming_headers=incoming_headers,
            ),
            200,
        )
    job_status["running"] = True
    job_status["current_job"] = inspect.currentframe().f_code.co_name

    pre_and_post_check()
    try:
        model_name = data["model_name"]
        print("model_name: ", model_name, "destn_path", destn_path)
    except (TypeError, KeyError) as e:
        job_status["running"] = False
        return (
            manual_response(
                content=f"Invalid JSON data: {e}",
                thinking=f"Invalid JSON data: {e}",
                incoming_headers=incoming_headers,
            ),
            400,
        )

    file_name = denormalize_model_name(data["model_name"])

    send_serial_command(
        f'cd {destn_path}; rm -fr {file_name}* && find . -type d -empty | while read -r dir; do rmdir "$dir"; done',
        timeout=300,
    )

    job_status["running"] = False
    return (
        manual_response(
            content="Model deleted",
            thinking="Model deleted",
            incoming_headers=incoming_headers,
        ),
        200,
    )


@app.route("/upload-file", methods=["GET", "POST"])
def upload_file():

    pre_and_post_check()

    if request.method == "POST":
        # Check if a file was submitted
        if "file" not in request.files:
            return "No file part"
        file = request.files["file"]

        # Check if the file is empty
        if file.filename == "":
            return "No file selected"

        # Save the file if it exists
        if file:
            filename = secure_filename(file.filename)
            process = subprocess.Popen(["./copy2fpga-x86.sh", filename], text=True)
            copy2fpgax86prints = "Starting copy2fpga-x86 and sending file..."
            print(copy2fpgax86prints)
            file.save(os.path.join(app.config["UPLOAD_FOLDER"], filename))

            script_path = "./recvFromHost "
            temporary_destination_path = request.form.get(
                "destination_file_path"
            )  # I've tested this on fpgax and it correctly gets the user-inputted file path
            command = (
                f"cd {exe_path}; {script_path} {temporary_destination_path}{filename}"
            )

            def scriptRecvFromHost():
                try:
                    result = send_serial_command(command)
                    job_status["result"] = result

                    print(result)

                    recv_output = result
                except subprocess.CalledProcessError as e:
                    job_status["result"] = f"Error: {e.stderr}"
                finally:
                    job_status["running"] = False

            thread = threading.Thread(target=scriptRecvFromHost)
            job_status = {"running": True, "result": "", "thread": thread}
            thread.start()
            thread.join()
            stdout, stderr = process.communicate()

        send_serial_command(f"cd {temporary_destination_path}; ls -lt", timeout=300)

        return render_template(
            "uploadtofpga.html",
            apple=process,
            recvoutput=f"On FPGA Target, recvFromHost completed ; transfered file:{filename} received ",
        )
    return render_template("upload.html")  # Display the upload form


def internal_restart_txe():
    command = f"cd /proj/rel/fpga/tsi/latest_sof_release; make all"

    process = subprocess.Popen(
        [command],
        shell=True,
        preexec_fn=os.setsid,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        bufsize=1,
        text=True,
    )

    start = time.time()
    try:
        for line in process.stdout:
            print("HOST:" + line)
            if any(
                phrase in line
                for phrase in [
                    "Global Reset exercised",
                    "release chip from reset called",  # For Pre Rel 37 where Make Juart Complete
                    "Use the IDE stop button or Ctrl-C to terminate",  # For Rel37 as Make Juart does not Complete
                ]
            ):
                os.killpg(os.getpgid(process.pid), signal.SIGTERM)
                break
            current = time.time()
            if current - start >= 1000:
                os.killpg(os.getpgid(process.pid), signal.SIGTERM)
    except Exception as e:
        os.killpg(os.getpgid(process.pid), signal.SIGTERM)
    finally:
        os.killpg(os.getpgid(process.pid), signal.SIGTERM)

    process.wait()

    restart_txe_serial_portion(exe_path)

    print("Finished Everything Hooray")


@app.route("/restart-txe", methods=["GET"])
def restart_txe_serial_command():

    pre_and_post_check()

    internal_restart_txe()

    return "Done"


@app.route("/health-check", methods=["GET"])
def health_check_serial_command():

    pre_and_post_check()

    command = f"uptime; free -h; df -h; top -b -n1"

    try:
        result = send_serial_command(command)
        return result, 200
    except subprocess.CalledProcessError as e:
        return f"Error executing script: {e.stderr}", 500


@app.route("/test", methods=["GET"])
def test_serial_command():

    pre_and_post_check()

    command = f"test"

    try:
        result = send_serial_command(command)
        return result, 200
    except subprocess.CalledProcessError as e:
        return f"Error executing script: {e.stderr}", 500


@app.route("/system-info", methods=["GET"])
def system_info_serial_command():

    pre_and_post_check()

    command = f"{exe_path}../install/tsi-version; uptime; lsmod; lscpu; lsblk"

    try:
        result = send_serial_command(command)
        return result, 200
    except subprocess.CalledProcessError as e:
        return f"Error executing script: {e.stderr}", 500


def manual_response(
    status="success",
    model="ollama",
    content=None,
    thinking=None,
    tool_calls=None,
    openai_tool_calls=None,
    name="Alice",
    id="12345",
    email="alice@example.com",
    role="admin",
    some_key="some_value",
    profile_data=None,
    incoming_headers=None,
):
    desired_keys = [
        "Authorization",
        "X-OpenWebUI-User-Name",
        "X-OpenWebUI-User-Id",
        "X-OpenWebUI-User-Email",
        "X-OpenWebUI-User-Role",
        "X-OpenWebUI-Chat-Id",
    ]

    response_headers = {
        key: incoming_headers[key] for key in desired_keys if key in incoming_headers
    }

    json_string = {
        "status": status,
        "model": model,
        "message": {
            "content": content,
            "thinking": thinking,
            "tool_calls": tool_calls,
            "openai_tool_calls": openai_tool_calls,
            "meta": profile_data,
        },
        "data": {
            "some_key": some_key,
        },
        "done_reason": "stop",
        "done": True,  # This is to indicate that we are one command at a time, not interactive
    }
    print("Response:\n", json.dumps(json_string), "\n")
    response = make_response(json.dumps(json_string))
    response_headers = {
        key: incoming_headers[key] for key in desired_keys if key in incoming_headers
    }
    response.headers = response_headers
    response.headers["Content-Type"] = "application/json"
    return response


def clean_up_json_string(string):
    # 1️⃣ Extract just the JSON-looking portion
    match = re.search(r"\{.*?\}", string)
    if match:
        json_candidate = match.group(0)

        # 2️⃣ Replace escape sequences
        cleaned = json_candidate.encode("utf-8").decode("unicode_escape")

        # 3️⃣ Load and parse JSON
        try:
            parsed = json.loads(cleaned)
            # print(json.dumps(parsed, indent=2))
            return parsed
        except json.JSONDecodeError as e:
            # print("JSON parsing failed:", e)
            return cleaned
    else:
        # print("No JSON object found")
        return string


def extract_final_output_after_chat_history(text):
    chat_history_phrase = "</chat_history>"
    if chat_history_phrase in text:
        # parts = text.split(chat_history_phrase)
        # filtered_text = parts[-1]  # content after the last tag
        filtered_text = text.split(chat_history_phrase, 1)[
            1
        ]  # Split once and take the second part
    else:
        filtered_text = text
    return filtered_text


def extract_chat_history(text):
    chat_history_phrase = "Chat History:"
    if chat_history_phrase in text:
        # parts = text.split(chat_history_phrase)
        # filtered_text = parts[-1]  # content after the last tag
        filtered_text = text.split(chat_history_phrase, 1)[
            1
        ]  # Split once and take the second part
    else:
        filtered_text = text
    return filtered_text


def extract_json_output(text):
    start_phrase = "JSON format:"
    if start_phrase in text:
        # parts = text.split(start_phrase)
        # filtered_text = parts[-1]  # content after the last tag
        filtered_text = text.split(start_phrase, 1)[
            1
        ]  # Split once and take the second part
    else:
        filtered_text = text
    return clean_up_json_string(filtered_text)


@app.route("/_app", methods=["POST", "GET"])
@app.route("/api/chats", methods=["POST", "GET"])
def chats():
    global job_status
    global parameters

    data = request.get_json()
    incoming_headers = dict(request.headers)
    print("Request:", data)
    if "options" in data:
        for item in parameters:
            if item in data["options"]:
                parameters[item] = data["options"][item]

    original_prompt = data["messages"][-1]["content"]
    flattened_prompt = re.sub(r"\s+", " ", original_prompt).strip()
    tmpprompt = flattened_prompt.replace('"', '\\"').encode("utf-8")
    # Read a custom environment variable, e.g., REGION
    region = os.getenv("REGION", "USA")  # Default to 'USA' if not set
    # Decide encoding based on region
    if region == "USA":
        prompt = tmpprompt.decode("utf-8")
    else:
        prompt = tmpprompt

    model = DEFAULT_MODEL

    if parameters["aottests"] == "yes":
        model_path = data["model"]

        # Use only the part before ':' for directory/file names
        model_dir = model_path.split(":", 1)[0]  # "Maykeye_TinyLLama-v0"

        # Build paths robustly
        script_path = os.path.join(model_dir, f"{model_dir}.sh")
        exec_path = os.path.join(model_dir, f"{model_dir}.exe")
        # Quote paths in shell commands to avoid issues with spaces/special chars
        aot_tests_dir = os.path.join(exe_path, "aot-tests/models")
        if model_dir.startswith("ArchesWeather-"):
            input_prompt = f"--input {safetensor_destn_path}/inputs/"
            output_prompt = f"--output {safetensor_destn_path}{model_dir}/output"
            command = f"cd {shlex.quote(aot_tests_dir)}; {shlex.quote(exec_path)} {input_prompt} {output_prompt}"
        else:
            command = f'cd {shlex.quote(aot_tests_dir)}; NORUN=1 source {shlex.quote(script_path)}; {shlex.quote(exec_path)} "{prompt}"'
    else:
        if parameters["target"] == "cpu":
            backend = "none"
        elif parameters["target"] == "opu":
            backend = "tSavorite"
        if "model" in data:
            model = data["model"]

        tokens = parameters["num_predict"]
        repeat_penalty = parameters["repeat_penalty"]
        batch_size = parameters["num_batch"]
        top_k = parameters["top_k"]
        top_p = parameters["top_p"]
        last_n = parameters["repeat_last_n"]
        context_length = parameters["num_ctx"]
        temp = parameters["temperature"]

        # Define the model path (update with actual paths)
        model_paths = {
            "tiny-llama": "tinyllama-vo-5m-para.gguf",
            "TinyLlama:latest": "Tiny-Llama-v0.3-FP32-1.1B-F32.gguf",
        }
        model_path = model_paths.get(model, "")
        if not model_path:
            model_path = model
        # Build llama-cli command
        # command = [
        #    "./llama-cli",
        #    "-p", prompt,
        #    "-m", model_path,
        #    "--device", backend,
        #    "--temp", "0",
        #    "--n-predict", tokens,
        #    "--repeat-penalty", "1",
        #    "--top-k", "0",
        #    "--top-p", "1"
        # ]
        script_path = "./run_llama_cli.sh"
        command = f'cd {exe_path}; {script_path} "{prompt}" {tokens} {model_path} {backend} {repeat_penalty} {batch_size} {top_k} {top_p} {last_n} {context_length} {temp}'

    if is_job_running() == True:
        return (
            manual_response(
                content=f"Server is busy. Current job: {job_status.get('current_job', 'Unknown')}. Please try again later.",
                thinking=None,
                profile_data=None,
                incoming_headers=incoming_headers,
            ),
            200,
        )
    job_status["running"] = True
    job_status["current_job"] = inspect.currentframe().f_code.co_name

    pre_and_post_check()

    def run_script(command, region):
        try:
            result = send_serial_command(
                command, DEFAULT_MODEL_COMMAND_RUN_TIMEOUT, region
            )
            if result:
                response_text = result
                # Remove the command from the beginning of the response if present
                if response_text.startswith(command):
                    response_text = response_text[len(command) :].lstrip()

                start_phrases = [
                    "llama_perf_sampler_print: ",
                    "OPU Profiling Results:",
                    "Profiling Results",
                    "LLAMA SP Profiling Results:",
                    "ArchesWeather Profiling Results:",
                ]

                matched_phrase = next(
                    (phrase for phrase in start_phrases if phrase in response_text),
                    None,
                )

                if matched_phrase:
                    filtered_text = response_text.split(matched_phrase, 1)[0]
                    formatted_text = response_text.split(matched_phrase, 1)[1]
                    if "Generated text:" in filtered_text:
                        filtered_text = filtered_text.split("Generated text:", 1)[1]
                    if matched_phrase == "ArchesWeather Profiling Results:":
                        output_file_phrase = "Saved output tensor to "
                        filtered_text = filtered_text.split(output_file_phrase, 1)[1]
                        filtered_text = filtered_text.strip().strip('"')
                else:
                    filtered_text = result
                    formatted_text = None
            else:
                filtered_text = (
                    "Result Empty: Desired phrase not found in the response."
                )
                formatted_text = None  # Or None, depending on your use case

            return filtered_text, formatted_text
        except subprocess.CalledProcessError as e:
            filtered_text = f"Error: {e.stderr}"
            job_status["result"] = filtered_text
            job_status["running"] = False
        return filtered_text, formatted_text

    filtered_text, profile_text = run_script(command, region)
    extracted_json = extract_json_output(filtered_text)
    chat_history = extract_chat_history(filtered_text)
    final_chat_output = extract_final_output_after_chat_history(chat_history)
    job_status["running"] = False
    return (
        manual_response(
            content=final_chat_output,
            thinking=chat_history,
            profile_data=profile_text,
            incoming_headers=incoming_headers,
        ),
        200,
    )


@app.route("/api/chat", methods=["POST", "GET"])
@app.route("/api/chat/completion", methods=["POST", "GET"])
@app.route("/api/chat/completed", methods=["POST", "GET"])
@app.route("/api/generate", methods=["POST", "GET"])
def chat():
    global job_status
    global parameters

    data = request.get_json()
    incoming_headers = dict(request.headers)
    print("Request:", data)
    if "options" in data:
        for item in parameters:
            if item in data["options"]:
                parameters[item] = data["options"][item]

    original_prompt = data["messages"][-1]["content"]
    flattened_prompt = re.sub(r"\s+", " ", original_prompt).strip()
    tmpprompt = flattened_prompt.replace('"', '\\"').encode("utf-8")
    # Read a custom environment variable, e.g., REGION
    region = os.getenv("REGION", "USA")  # Default to 'USA' if not set
    # Decide encoding based on region
    if region == "USA":
        prompt = tmpprompt.decode("utf-8")
    else:
        prompt = tmpprompt

    model = DEFAULT_MODEL

    if parameters["aottests"] == "yes":
        model_path = data["model"]

        # Use only the part before ':' for directory/file names
        model_dir = model_path.split(":", 1)[0]  # "Maykeye_TinyLLama-v0"

        # Build paths robustly
        script_path = os.path.join(model_dir, f"{model_dir}.sh")
        exec_path = os.path.join(model_dir, f"{model_dir}.exe")

        # Quote paths in shell commands to avoid issues with spaces/special chars
        aot_tests_dir = os.path.join(exe_path, "aot-tests/models")

        if model_dir.startswith("ArchesWeather-"):
            input_prompt = f"--input {safetensor_destn_path}inputs/"
            output_prompt = f"--output {safetensor_destn_path}{model_dir}/output"
            command = f"cd {shlex.quote(aot_tests_dir)}; {shlex.quote(exec_path)} {input_prompt} {output_prompt}"
        else:
            command = f'cd {shlex.quote(aot_tests_dir)}; NORUN=1 source {shlex.quote(script_path)}; {shlex.quote(exec_path)} "{prompt}"'
    else:
        if parameters["target"] == "cpu":
            backend = "none"
        elif parameters["target"] == "opu":
            backend = "tSavorite"
        if "model" in data:
            model = data["model"]

        tokens = parameters["num_predict"]
        repeat_penalty = parameters["repeat_penalty"]
        batch_size = parameters["num_batch"]
        top_k = parameters["top_k"]
        top_p = parameters["top_p"]
        last_n = parameters["repeat_last_n"]
        context_length = parameters["num_ctx"]
        temp = parameters["temperature"]

        # Define the model path (update with actual paths)
        model_paths = {
            "tiny-llama": "tinyllama-vo-5m-para.gguf",
            "TinyLlama:latest": "Tiny-Llama-v0.3-FP32-1.1B-F32.gguf",
        }
        model_path = model_paths.get(model, "")
        if not model_path:
            model_path = model
        # Build llama-cli command
        # command = [
        #    "./llama-cli",
        #    "-p", prompt,
        #    "-m", model_path,
        #    "--device", backend,
        #    "--temp", "0",
        #    "--n-predict", tokens,
        #    "--repeat-penalty", "1",
        #    "--top-k", "0",
        #    "--top-p", "1"
        # ]
        script_path = "./run_llama_cli.sh"
        command = f'cd {exe_path}; {script_path} "{prompt}" {tokens} {model_path} {backend} {repeat_penalty} {batch_size} {top_k} {top_p} {last_n} {context_length} {temp}'

    if is_job_running() == True:
        return (
            manual_response(
                content=f"Server is busy. Current job: {job_status.get('current_job', 'Unknown')}. Please try again later.",
                thinking=None,
                profile_data=None,
                incoming_headers=incoming_headers,
            ),
            200,
        )
    job_status["running"] = True
    job_status["current_job"] = inspect.currentframe().f_code.co_name

    pre_and_post_check()

    def run_script(command, region):
        try:
            result = send_serial_command(
                command, DEFAULT_MODEL_COMMAND_RUN_TIMEOUT, region
            )
            if result:
                response_text = result
                # Remove the command from the beginning of the response if present
                if response_text.startswith(command):
                    response_text = response_text[len(command) :].lstrip()

                start_phrases = [
                    "llama_perf_sampler_print: ",
                    "OPU Profiling Results:",
                    "Profiling Results ",
                    "LLAMA SP Profiling Results:",
                    "ArchesWeather Profiling Results:",
                ]
                matched_phrase = next(
                    (phrase for phrase in start_phrases if phrase in response_text),
                    None,
                )

                if matched_phrase:
                    filtered_text = response_text.split(matched_phrase, 1)[0]
                    formatted_text = response_text.split(matched_phrase, 1)[1]
                    if "Generated text:" in filtered_text:
                        filtered_text = filtered_text.split("Generated text:", 1)[1]
                    if matched_phrase == "ArchesWeather Profiling Results:":
                        output_file_phrase = "Saved output tensor to "
                        filtered_text = filtered_text.split(output_file_phrase, 1)[1]
                        filtered_text = filtered_text.strip().strip('"')
                else:
                    filtered_text = result
                    formatted_text = None
            else:
                filtered_text = (
                    "Result Empty: Desired phrase not found in the response."
                )
                formatted_text = None
                job_status["result"] = filtered_text

            return filtered_text, formatted_text
        except subprocess.CalledProcessError as e:
            filtered_text = f"Error: {e.stderr}"
            job_status["result"] = filtered_text
            job_status["running"] = False
        return filtered_text, formatted_text

    filtered_text, profile_text = run_script(command, region)
    extracted_json = extract_json_output(filtered_text)
    chat_history = extract_chat_history(filtered_text)
    final_chat_output = extract_final_output_after_chat_history(chat_history)
    job_status["running"] = False

    return (
        manual_response(
            content=final_chat_output,
            thinking=chat_history,
            profile_data=profile_text,
            incoming_headers=incoming_headers,
        ),
        200,
    )


def qemu_restart_txe():
    command = f"reboot -f\n"
    restart_txe_serial_portion(command)
    initialize_shell()
    print("Finished Rebooting")


@app.route("/api/restart-txe", methods=["GET", "POST"])
def restart_txe_ollama_serial_command():
    global job_status
    global parameters
    incoming_headers = dict(request.headers)

    pre_and_post_check()
    if ssh:
        qemu_restart_txe()
    else:
        internal_restart_txe()
    job_status["running"] = False

    return (
        manual_response(
            content="Restarted OPU",
            thinking="Restarted OPU",
            incoming_headers=incoming_headers,
        ),
        200,
    )


def fetch_aot_models_file_names():
    models = {"models": []}

    try:
        project_dir = pathlib.Path(tsi_customer_path).resolve()  # safer than 'cd'
        result = subprocess.run(
            ["make", "list-models"],
            cwd=project_dir,
            capture_output=True,
            text=True,
            check=True,
        )
        stdout = result.stdout

        # Parse lines after "Available models:" until a blank line or non-model section
        lines = stdout.splitlines()
        collecting = False
        for line in lines:
            stripped = line.strip()

            if not collecting:
                if stripped.lower().startswith("available models:"):
                    collecting = True
                continue

            # Stop collecting at empty line or when instruction/help section starts
            if stripped == "":
                break
            if stripped.lower().startswith("to build") or stripped.lower().startswith(
                "to run"
            ):
                break

            # Remove leading bullets/indent; accept typical model name characters
            models["models"].append({"name": stripped, "model": stripped})

    except Exception as e:
        print(f"process completed with exception: {e}")
        # Return the (possibly empty) models dict
        return models

    return models


@app.route("/uploadaottest", methods=["GET"])
def aottest_upload_serial_command(incoming_headers):

    # pre_and_post_check()
    remote_dir = safetensor_destn_path
    models = fetch_aot_models_file_names()

    # Iterate until name is empty
    for item in models["models"]:
        if not item["name"]:  # Stop when name is empty
            break

        if item["name"] == "Mistral-7B-v0.1":  # Don't upload Mistral model right now
            continue

        new_file_name = f"{remote_dir}/{item['name']}.tz"
        actual_new_file_name = f"{remote_dir}/{item['name']}"
        current_file_name = f"{pytorch_model_path}/{item['name']}.tz"
        file_name = f"{item['name']}.tz"
        actual_file_name = f"{item['name']}"

        preliminary_target_check = send_serial_command(
            f"cd {remote_dir}; md5sum {file_name}"
        )

        try:
            preliminary_host_check = subprocess.run(
                ["md5sum", current_file_name],
                capture_output=True,
                text=True,
                check=True,
            )
        except Exception as e:
            job_status["running"] = False
            return (
                manual_response(
                    content=f"File checksum failed: {e}",
                    thinking=f"File checksum failed: {e}",
                    incoming_headers=incoming_headers,
                ),
                500,
            )

        if preliminary_target_check.split()[0].replace(
            "\x00", ""
        ) == preliminary_host_check.stdout.split()[0].replace("\x00", ""):
            job_status["running"] = False
            return (
                manual_response(
                    content="File Already Exists",
                    thinking="File Already Exists",
                    incoming_headers=incoming_headers,
                ),
                200,
            )

        send_serial_command(f"cd {remote_dir}; rm {file_name}", timeout=300)

        try:
            file_size = os.path.getsize(current_file_name)
            file_obj = open(current_file_name, "rb")
        except Exception as e:
            job_status["running"] = False
            return (
                manual_response(
                    content=f"File open failed: {e}",
                    thinking=f"File open failed: {e}",
                    incoming_headers=incoming_headers,
                ),
                500,
            )

        full_path = file_obj.name
        full_path = os.path.abspath(current_file_name)
        try:
            actual_transfer(remote_dir, file_obj, file_size)
        except Exception as e:
            job_status["running"] = False
            return (
                manual_response(
                    content=f"File transfer failed: {e}",
                    thinking=f"File transfer failed: {e}",
                    incoming_headers=incoming_headers,
                ),
                500,
            )

        send_serial_command(f"cd {remote_dir}; tar xvzf {file_name}", timeout=300)
        send_serial_command(
            f"cd {aottests_model_path}; ln -s {actual_new_file_name} {aottests_model_path}{actual_file_name}",
            timeout=300,
        )

        if ssh:
            job_status["running"] = False
            return (
                manual_response(
                    content="File Download Done",
                    thinking="File Download Done",
                    incoming_headers=incoming_headers,
                ),
                200,
            )

        print("Listing out existing files")
        send_serial_command(f"cd {remote_dir}; ls -lt", timeout=300)
        send_serial_command(f"cd {aottests_model_path}; ls -lt", timeout=300)

        target_check_sum = send_serial_command(
            f"cd {remote_dir}; md5sum {file_name}", timeout=300
        )

        job_status["running"] = False

        if target_check_sum.split()[0].replace(
            "\x00", ""
        ) != preliminary_host_check.stdout.split()[0].replace("\x00", ""):
            return (
                manual_response(
                    content="Failed checksum match",
                    thinking="Failed checksum match",
                    incoming_headers=incoming_headers,
                ),
                400,
            )

    return (
        manual_response(
            content="File Download Done",
            thinking="File Download Done",
            incoming_headers=incoming_headers,
        ),
        200,
    )


@app.route("/api/uploadaottest", methods=["GET", "POST"])
def aottest_upload_ollama_serial_command():
    incoming_headers = dict(request.headers)
    if is_job_running() == True:
        return (
            manual_response(
                content=f"Server is busy. Current job: {job_status.get('current_job', 'Unknown')}. Please try again later.",
                thinking=None,
                profile_data=None,
                incoming_headers=incoming_headers,
            ),
            200,
        )

    job_status["running"] = True
    job_status["current_job"] = inspect.currentframe().f_code.co_name
    result, error = aottest_upload_serial_command(incoming_headers)
    job_status["running"] = False
    return (
        manual_response(
            content="File Download Complete",
            thinking="AOT Test Results",
            incoming_headers=incoming_headers,
        ),
        error,
    )


@app.route("/uploadpytorchinput", methods=["GET"])
def pytorch_upload_input_file_command(incoming_headers, file_name, path):

    # pre_and_post_check()
    remote_dir = safetensor_destn_path + "inputs/"

    transfer_filename = os.path.basename(path)

    try:
        file_size = os.path.getsize(path)
        file_obj = open(path, "rb")
    except Exception as e:
        job_status["running"] = False
        return (
            manual_response(
                content=f"File open failed: {e}",
                thinking=f"File open failed: {e}",
                incoming_headers=incoming_headers,
            ),
            500,
        )

    full_path = file_obj.name

    preliminary_target_check = send_serial_command(
        f"cd {remote_dir}; md5sum {file_name}"
    )

    try:
        preliminary_host_check = subprocess.run(
            ["md5sum", full_path],
            capture_output=True,
            text=True,
            check=True,
        )
    except Exception as e:
        job_status["running"] = False
        return (
            manual_response(
                content=f"File checksum failed: {e}",
                thinking=f"File checksum failed: {e}",
                incoming_headers=incoming_headers,
            ),
            500,
        )

    if preliminary_target_check.split()[0].replace(
        "\x00", ""
    ) == preliminary_host_check.stdout.split()[0].replace("\x00", ""):
        job_status["running"] = False
        return (
            manual_response(
                content="File Already Exists",
                thinking="File Already Exists",
                incoming_headers=incoming_headers,
            ),
            200,
        )

    send_serial_command(f"cd {remote_dir}; rm {file_name}", timeout=300)

    try:
        actual_transfer(remote_dir, file_obj, file_size)
    except Exception as e:
        job_status["running"] = False
        return (
            manual_response(
                content=f"File transfer failed: {e}",
                thinking=f"File transfer failed: {e}",
                incoming_headers=incoming_headers,
            ),
            500,
        )

    if ssh:
        job_status["running"] = False
        return (
            manual_response(
                content="File Download Done",
                thinking="File Download Done",
                incoming_headers=incoming_headers,
            ),
            200,
        )

    send_serial_command(
        f"cd {remote_dir}; mv {transfer_filename} {file_name}; ls -lt", timeout=300
    )

    target_check_sum = send_serial_command(
        f"cd {remote_dir}; md5sum {file_name}", timeout=300
    )

    job_status["running"] = False

    if target_check_sum.split()[0].replace(
        "\x00", ""
    ) != preliminary_host_check.stdout.split()[0].replace("\x00", ""):
        return (
            manual_response(
                content="Failed checksum match",
                thinking="Failed checksum match",
                incoming_headers=incoming_headers,
            ),
            400,
        )

    return (
        manual_response(
            content="PyTorch Input File upload Done",
            thinking="PyTorch Input File upload Done",
            incoming_headers=incoming_headers,
        ),
        200,
    )


@app.route("/api/uploadpytorchinput", methods=["GET", "POST"])
def pytorch_upload_input_file():
    incoming_headers = dict(request.headers)
    if is_job_running() == True:
        return (
            manual_response(
                content=f"Server is busy. Current job: {job_status.get('current_job', 'Unknown')}. Please try again later.",
                thinking=None,
                profile_data=None,
                incoming_headers=incoming_headers,
            ),
            200,
        )

    data = None
    filename = None

    # Try JSON body first (POST)
    if request.is_json:
        data = request.get_json(silent=True) or {}
        filename = data.get("file")
        full_path = data.get("path")

    # Fallback to query string if not provided in JSON (GET or POST)
    if not filename:
        filename = request.args.get("file")
        full_path = request.args.get("full_path")

    if not filename:
        # Bad request if filename is missing
        return (
            jsonify(
                {
                    "status": "error",
                    "message": "Missing 'file' parameter in JSON body or query string",
                }
            ),
            400,
        )
    job_status["running"] = True
    job_status["current_job"] = inspect.currentframe().f_code.co_name
    result, error = pytorch_upload_input_file_command(
        incoming_headers, filename, full_path
    )
    job_status["running"] = False
    return (
        manual_response(
            content="PyTorch Input File Upload Complete",
            thinking="PyTorch Input File",
            incoming_headers=incoming_headers,
        ),
        error,
    )


@app.route("/aottest", methods=["GET"])
def aottest_serial_command():

    # pre_and_post_check()
    command = f"{exe_path}/aot-tests/tests-torch/add/add.sh"
    print(command)
    try:
        result = send_serial_command(command)
        return result, 200
    except subprocess.CalledProcessError as e:
        return f"Error executing script: {e.stderr}", 500


@app.route("/api/aottest", methods=["GET", "POST"])
def aottest_ollama_serial_command():
    incoming_headers = dict(request.headers)
    if is_job_running() == True:
        return (
            manual_response(
                content=f"Server is busy. Current job: {job_status.get('current_job', 'Unknown')}. Please try again later.",
                thinking=None,
                profile_data=None,
                incoming_headers=incoming_headers,
            ),
            200,
        )

    job_status["running"] = True
    job_status["current_job"] = inspect.currentframe().f_code.co_name
    result, error = aottest_serial_command()
    job_status["running"] = False
    return (
        manual_response(
            # content=result,
            content="AOT Tests compiled",
            thinking="AOT Test Results",
            incoming_headers=incoming_headers,
        ),
        error,
    )


def find_picocom_processes():
    """Return a list of psutil.Process objects for processes whose name or cmdline contains 'picocom'."""
    matches = []
    for proc in psutil.process_iter(["pid", "name", "cmdline"]):
        try:
            name = (proc.info.get("name") or "").lower()
            cmdline = " ".join(proc.info.get("cmdline") or []).lower()
            if "picocom" in name or "picocom" in cmdline:
                matches.append(proc)
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            # Process died or we don't have permission—skip it
            continue
    return matches


def terminate_process(proc: psutil.Process, timeout=5.0):
    """
    Try graceful termination first, then force kill if needed.
    Returns True if the process is gone, False otherwise.
    """
    try:
        # 1) Try SIGTERM (graceful)
        proc.terminate()  # sends SIGTERM on POSIX, TerminateProcess on Windows
    except (psutil.NoSuchProcess, psutil.AccessDenied):
        return False

    try:
        psutil.wait_procs([proc], timeout=timeout)
    except psutil.TimeoutExpired:
        pass

    if proc.is_running():
        try:
            # 2) Force kill (SIGKILL on POSIX)
            proc.kill()
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass

        # Give it a moment to die
        time.sleep(0.2)

    return not proc.is_running()


def kill_all_picocom(timeout=5.0):
    """
    Finds all picocom processes and kills them.
    Returns a dict with process IDs and status.
    """
    results = []
    procs = find_picocom_processes()
    for proc in procs:
        try:
            pid = proc.pid
            cmdline = " ".join(proc.cmdline())
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pid = None
            cmdline = ""

        success = terminate_process(proc, timeout=timeout)
        results.append({"pid": pid, "cmdline": cmdline, "killed": success})
    return results


@app.route("/killpicocom", methods=["GET"])
def killpicocom_command():
    # pre_and_post_check()
    try:
        result = kill_all_picocom()
        return result, 200
    except subprocess.CalledProcessError as e:
        return f"Error executing script: {e.stderr}", 500


@app.route("/api/killpicocom", methods=["GET", "POST"])
def ollama_killpicocom_command():
    incoming_headers = dict(request.headers)
    if is_job_running() == True:
        return (
            manual_response(
                content=f"Server is busy. Current job: {job_status.get('current_job', 'Unknown')}. Please try again later.",
                thinking=None,
                profile_data=None,
                incoming_headers=incoming_headers,
            ),
            200,
        )

    job_status["running"] = True
    job_status["current_job"] = inspect.currentframe().f_code.co_name
    result, error = killpicocom_command()
    job_status["running"] = False
    return (
        manual_response(
            # content=result,
            content="picocom killed",
            thinking="picocom kille",
            incoming_headers=incoming_headers,
        ),
        error,
    )


@app.route("/api/system-info", methods=["GET", "POST"])
def system_info_ollama_serial_command():
    incoming_headers = dict(request.headers)
    if is_job_running() == True:
        return (
            manual_response(
                content=f"Server is busy. Current job: {job_status.get('current_job', 'Unknown')}. Please try again later.",
                thinking=None,
                profile_data=None,
                incoming_headers=incoming_headers,
            ),
            200,
        )

    job_status["running"] = True
    job_status["current_job"] = inspect.currentframe().f_code.co_name
    result, error = system_info_serial_command()
    job_status["running"] = False
    return (
        manual_response(
            content=result, thinking="System Info", incoming_headers=incoming_headers
        ),
        error,
    )


@app.route("/api/health-check", methods=["GET", "POST"])
def health_check_ollama_serial_command():
    incoming_headers = dict(request.headers)
    if is_job_running() == True:
        return (
            manual_response(
                content=f"Server is busy. Current job: {job_status.get('current_job', 'Unknown')}. Please try again later.",
                thinking=None,
                profile_data=None,
                incoming_headers=incoming_headers,
            ),
            200,
        )

    job_status["running"] = True
    job_status["current_job"] = inspect.currentframe().f_code.co_name
    result, error = health_check_serial_command()
    job_status["running"] = False

    return (
        manual_response(
            content=result, thinking="Health Check", incoming_headers=incoming_headers
        ),
        error,
    )


def aborttask():
    try:
        result = abort_serial_portion()
        return result, 200
    except subprocess.CalledProcessError as e:
        return f"Error executing script: {e.stderr}", 500


@app.route("/api/abort-task", methods=["GET", "POST"])
def abort_task_ollama_serial_command():
    incoming_headers = dict(request.headers)
    result, error = aborttask()
    if is_job_running() == True:
        job_status["running"] = False
    return (
        manual_response(
            content=result, thinking="Abort Task", incoming_headers=incoming_headers
        ),
        error,
    )


def initiate_serial_download(filename):
    result = initiate_serial_download_command(filename)
    try:
        cmd = "rz < /dev/ttyUSB3 > /dev/ttyUSB3"

        result = subprocess.run(
            cmd,
            shell=True,
            capture_output=True,
            text=True,
            check=True,
        )
    except Exception as e:
        return f"Error running rz: {e.stderr}", 500
    return result, 200


@app.route("/api/initiate-download", methods=["GET", "POST"])
def initiate_download_ollama_serial_command():
    incoming_headers = dict(request.headers)

    data = None
    filename = None

    # Try JSON body first (POST)
    if request.is_json:
        data = request.get_json(silent=True) or {}
        filename = data.get("file")

    # Fallback to query string if not provided in JSON (GET or POST)
    if not filename:
        filename = request.args.get("file")

    if not filename:
        # Bad request if filename is missing
        return (
            jsonify(
                {
                    "status": "error",
                    "message": "Missing 'file' parameter in JSON body or query string",
                }
            ),
            400,
        )

    result, error = initiate_serial_download(filename)
    if is_job_running() == True:
        job_status["running"] = False
    return (
        manual_response(
            content="File copied to host",
            thinking="Initiated the download",
            incoming_headers=incoming_headers,
        ),
        error,
    )


@app.route("/submit", methods=["POST"])
def submit():

    pre_and_post_check()

    global job_status

    if job_status["running"]:
        return "<h2>A model is already running. Please wait or abort.</h2>"

    # ./run_llama_cli.sh "my cat's name" "10" "tinyllama-vo-5m-para.gguf" "none"
    model = request.form.get("model")
    backend = request.form.get("backend")
    tokens = request.form.get("tokens")
    prompt = request.form.get("prompt")
    repeat_penalty = request.form.get("repeat-penalty", DEFAULT_REPEAT_PENALTY)
    batch_size = request.form.get("batch-size", DEFAULT_BATCH_SIZE)
    top_k = request.form.get("top-k", DEFAULT_TOP_K)
    top_p = request.form.get("top-p", DEFAULT_TOP_P)
    last_n = request.form.get("last-n", DEFAULT_LAST_N)
    context_length = request.form.get("context-length", DEFAULT_CONTEXT_LENGTH)
    temp = request.form.get("temp", DEFAULT_TEMP)

    # Define the model path (update with actual paths)
    model_paths = {
        "tiny-llama": "tinyllama-vo-5m-para.gguf",
        "Tiny-llama-F32": "Tiny-Llama-v0.3-FP32-1.1B-F32.gguf",
    }

    model_path = model_paths.get(model, "")
    if not model_path:
        model_path = model

    # Build llama-cli command
    # command = [
    #    "./llama-cli",
    #    "-p", prompt,
    #    "-m", model_path,
    #    "--device", backend,
    #    "--temp", "0",
    #    "--n-predict", tokens,
    #    "--repeat-penalty", "1",
    #    "--top-k", "0",
    #    "--top-p", "1"
    # ]

    script_path = "./run_llama_cli.sh"
    command = f'cd {exe_path}; {script_path} "{prompt}" {tokens} {model_path} {backend} {repeat_penalty} {batch_size} {top_k} {top_p} {last_n} {context_length} {temp}'

    def run_script():
        try:
            result = send_serial_command(command)
            job_status["result"] = result
        except subprocess.CalledProcessError as e:
            job_status["result"] = f"Error: {e.stderr}"
        finally:
            time.sleep(max(10, int(tokens) / 5))
            job_status["running"] = False

    thread = threading.Thread(target=run_script)
    job_status = {"running": True, "result": "", "thread": thread}
    thread.start()

    return render_template("processing.html")


@app.route("/status")
def status():

    pre_and_post_check()

    if job_status["running"]:
        return "running"
    else:
        return "done"


@app.route("/result")
def result():

    return render_template("result.html", output=job_status["result"])


"""
Need to revert to an older version of Werkzeug to work!:

sudo python3 -m venv flasktest
source flasktest/bin/activate
sudo pip install "Werkzeug<3.0"

MISC. INFORMATION:

Takes around 2 minutes and 10 seconds to fully complete
At the end you should see the message: Finished Everything Hooray

"""


@app.route("/abort")
def abort():

    global job_status

    if job_status["running"] and job_status["thread"].is_alive():
        # Use subprocess.Popen + pid handling instead for real process termination
        job_status["running"] = False
        job_status["result"] = "Aborted by user."
        abort_serial_portion()
        internal_restart_txe()
        return "<h2>Job aborted.</h2><a href='/'>Home</a>"
    return "<h2>No job running.</h2><a href='/'>Home</a>"


import atexit


def cleanup():
    global ssh, shell
    close_shell(ssh, shell)


atexit.register(cleanup)

if __name__ == "__main__":
    if initialization_done is not True:
        initialize_shell()
        atexit.register(cleanup)
    app.run(debug=True, port=5001)
