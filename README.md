# media_pipe_ros2
<!-- ABOUT THE PROJECT -->
## About The Project
ROS2 package that utilizes the MediaPipe library.
https://mediapipe.dev/

Functionalities:
- [ ] Face Detection
- [x] Face Mesh
- [ ] Iris
- [x] Hands
- [x] Pose
- [x] Holistic
- [ ] Selfie Segmentation
- [ ] Hair Segmentation
- [ ] Object Detection
- [ ] Box Tracking
- [ ] Instant Motion Tracking
- [ ] Objectron
- [ ] KNIFT
- [ ] AutoFlip
- [ ] MediaSequence
- [ ] YouTube 8M

## Future Functionalities
- TBD

## Known Bugs
- Alignment issues of the landmark and its x and y pixels, especially at greater distances (>1m).
- Node does not determine difference between foreground and background depths when a shadow occurs. Example, when the hand is in front of the face, the face landmarks are erroneously given the hand's depth and should be given a fallback value within the planar range of the face. 

<!-- GETTING STARTED -->
## Getting Started

### Prerequisites
This guide assumes a **fresh Ubuntu 24.04 (Noble Numbat)** install with nothing else set up — that's the only OS ROS2 Jazzy publishes binary packages for, so it's the only one these instructions target (other distros would mean building ROS2 from source, which is out of scope here). Check your version with `lsb_release -a`.

* **ROS2 Jazzy** (skip this whole block if `ros2 --version` already works)
  ```bash
  # 1. UTF-8 locale (needed by ROS2 tooling)
  sudo apt update && sudo apt install -y locales
  sudo locale-gen en_US en_US.UTF-8
  sudo update-locale LC_ALL=en_US.UTF-8 LANG=en_US.UTF-8
  export LANG=en_US.UTF-8

  # 2. Enable the Ubuntu Universe repo
  sudo apt install -y software-properties-common
  sudo add-apt-repository universe

  # 3. Add the ROS2 apt repository
  sudo apt update && sudo apt install -y curl
  ROS_APT_SOURCE_VERSION=$(curl -s https://api.github.com/repos/ros-infrastructure/ros-apt-source/releases/latest | grep -F "tag_name" | awk -F'"' '{print $4}')
  curl -L -o /tmp/ros2-apt-source.deb "https://github.com/ros-infrastructure/ros-apt-source/releases/download/${ROS_APT_SOURCE_VERSION}/ros2-apt-source_${ROS_APT_SOURCE_VERSION}.$(. /etc/os-release && echo ${UBUNTU_CODENAME:-${VERSION_CODENAME}})_all.deb"
  sudo dpkg -i /tmp/ros2-apt-source.deb

  # 4. Install ROS2 Jazzy (Desktop includes RViz + demos; this project opens GUI windows, so Desktop is recommended over ros-base)
  sudo apt update && sudo apt full-upgrade -y
  sudo apt install -y ros-jazzy-desktop ros-dev-tools   # ros-dev-tools = colcon, rosdep, vcstool, etc.

  # 5. Initialize rosdep (one-time per machine) and source ROS2 for this shell
  sudo rosdep init
  rosdep update
  source /opt/ros/jazzy/setup.bash
  ```
  Add `source /opt/ros/jazzy/setup.bash` to your `~/.bashrc` so every new shell has ROS2 available.

* **Important: use a USB3 (SuperSpeed / blue) port for the camera.** The D435 streams RGB + Depth simultaneously, which exceeds USB2 bandwidth. On USB2 the driver will start and report "RealSense Node Is Up!", but you'll get a steady stream of `XXX Hardware Notification: Incomplete video frame detected! ... Frame Corrupted` warnings and no image data will actually reach the detector node. Check what a device is connected as with:
  ```bash
  lsusb -t   # look for your camera's Driver=uvcvideo line: 480M = USB2 (too slow), 5000M+ = USB3 (correct)
  ```

* **Intel RealSense SDK** (as of 2026, Intel spun RealSense out as "RealSense AI" — the SDK now lives at realsenseai.com, not intel.com)
  ```bash
  sudo apt install -y gnupg curl
  sudo mkdir -p /etc/apt/keyrings
  curl -sSf https://librealsense.realsenseai.com/Debian/librealsenseai.asc | gpg --dearmor | sudo tee /etc/apt/keyrings/librealsenseai.gpg > /dev/null
  echo "deb [signed-by=/etc/apt/keyrings/librealsenseai.gpg] https://librealsense.realsenseai.com/Debian/apt-repo $(lsb_release -cs) main" | sudo tee /etc/apt/sources.list.d/librealsense.list
  sudo apt-get update
  sudo apt-get install -y librealsense2-utils librealsense2-dev
  ```
  Optionally, also install the DKMS kernel module (adds hardware-timestamp/metadata support). It's only pre-built for HWE kernels 5.15/5.19/6.5, so on a newer kernel (check with `uname -r`) the build may fail — that's fine, basic streaming works without it via the mainline in-kernel UVC driver. Installing it may also prompt for a Secure Boot MOK password on next reboot.
  ```bash
  sudo apt-get install -y librealsense2-dkms
  ```
  Verify the camera is detected:
  ```bash
  rs-enumerate-devices --short
  ```
  If it comes back empty, unplug and replug the camera (the SDK install adds udev rules that need the device to be re-enumerated to take effect) and try again.

  The ROS2 wrapper (`realsense2_camera`) doesn't need a separate manual install — it's declared as a dependency in this package's `package.xml` and gets pulled in automatically by `rosdep` in the Installation step below.

* **Python dependencies: OpenCV, MediaPipe, NumPy**
  <br>MediaPipe is not compatible with NumPy 2.0+, so pin `numpy<2`. These need to be importable by whichever `python3` ROS2/colcon uses to build and run the nodes (system `python3` by default). Either install them system-wide, or use a venv created with `--system-site-packages` so it still sees `rclpy`, `cv_bridge`, etc.:
  ```bash
  # Option A: system-wide
  pip install --break-system-packages opencv-python mediapipe 'numpy<2'

  # Option B: venv (keeps system Python clean)
  python3 -m venv --system-site-packages ~/mp_ros2_venv
  source ~/mp_ros2_venv/bin/activate
  pip install opencv-python mediapipe 'numpy<2'
  ```
  If using the venv, activate it before `colcon build` (below) and before every `ros2 launch`/`ros2 run`, in addition to sourcing ROS2.
  
### Installation
This repository is itself a ROS2 workspace root (`src/` contains the `media_pipe_ros2` and `media_pipe_ros2_msg` packages; `build/`, `install/`, `log/` are gitignored at the repo root). Clone it and build directly — no need to nest it inside another workspace.
1. Clone the repository.
   ```bash
   sudo apt install -y git
   git clone https://github.com/LAIR-Lab/mp_ros2.git
   cd mp_ros2
   ```
2. Install this workspace's ROS2 package dependencies (pulls in `realsense2_camera`, `cv_bridge`, `message_filters`, etc. per each package's `package.xml`).
   ```bash
   source /opt/ros/jazzy/setup.bash
   rosdep install --from-paths src --ignore-src -r -y
   ```
3. Build with colcon (activate your venv first if you used Option B for the Python deps above).
   ```bash
   colcon build --merge-install
   ```
<!-- USAGE EXAMPLES -->
## Usage

A graphical window is opened by the node (via OpenCV) to visualize detections, so you need an X11 display. If you're on Wayland, switch to Xorg first: on the login screen, select your user, click the gear icon in the bottom right, and select `Ubuntu on Xorg`.

```bash
source /opt/ros/jazzy/setup.bash # source ROS2
source install/setup.bash        # source this workspace
# If you installed Python deps in a venv, also: source ~/mp_ros2_venv/bin/activate

ros2 launch media_pipe_ros2 mp.launch.py
```
This launches three nodes together: the `realsense2_camera` driver, the `detector` (MediaPipe holistic detection), and a `visualization` node (publishes RViz markers). The camera feed with landmark overlays will open in its own window; detections are also published to `/mediapipe/human_holistic_list` for other nodes to consume.

Can be launched with the following toggleable parameters: <br>
| Parameter | True (Default) | False |
|----------|----------|----------|
| face_on:=   | Detects face | Does not detect face |
| pose_on:=  | Detects pose | Does not detect pose |
| hands_on:=  | Detects hands | Does not detect hands |
| open_window:=  | Opens separate video window for visualization | Does not open window |

## Troubleshooting
- **`XXX Hardware Notification: Incomplete video frame detected! ... Frame Corrupted` spamming the log, no detections happening**: the camera is on a USB2 port. Check with `lsusb -t` — the camera's `uvcvideo` line should read `5000M` or higher, not `480M`. Move the cable to a USB3 (blue/SS) port.
- **`Warning: Parameter 'X' is not supported` for `camera_ns`, `pose_on`, `hands_on`, etc. at launch**: harmless. `mp.launch.py` declares these LaunchConfigurations for its own nodes, but they leak into the included `realsense2_camera` launch description's argument scan too; the RealSense node ignores them and starts normally.

<!-- CONTACT -->
## Contact

Dieisson Martinelli - dmartinelli1997@gmail.com
