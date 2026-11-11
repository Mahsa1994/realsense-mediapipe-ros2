"""
Record the lavalier mic from inside the video node's process.

This runs the audio_recorder package's own node, so the topics, parameters,
log lines and warnings are exactly those of
`ros2 launch audio_recorder audio_recorder.launch.py` (runbook step 5). It
spins on a background thread because the video loop blocks the main thread.

Audio parameters go on the video node's command line, e.g.
`ros2 run media_pipe_ros2 holistic_detector --ros-args -p capture_volume:=120`.
"""

import threading

from audio_recorder.audio_recorder_node import AudioRecorderNode
from rclpy.executors import ExternalShutdownException, SingleThreadedExecutor


def start_audio():
    node = AudioRecorderNode()
    executor = SingleThreadedExecutor()
    executor.add_node(node)

    def spin():
        try:
            executor.spin()
        except (KeyboardInterrupt, ExternalShutdownException):
            pass
        finally:
            node.destroy_node()

    threading.Thread(target=spin, daemon=True).start()
    return node
