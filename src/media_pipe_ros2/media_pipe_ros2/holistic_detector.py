import rclpy
from media_pipe_ros2.audio_capture import start_audio
import cv2
import mediapipe as mp
from rclpy.node import Node
from media_pipe_ros2_msg.msg import HandPoint,HandPoint,MediaPipeHumanHand,MediaPipeHumanHolisticList
from mediapipe.python.solutions.pose import PoseLandmark
from mediapipe.framework.formats import landmark_pb2
from sensor_msgs.msg import CompressedImage
from rcl_interfaces.msg import ParameterDescriptor
mp_drawing = mp.solutions.drawing_utils
mp_holistic = mp.solutions.holistic
mp_hands = mp.solutions.hands
mp_pose = mp.solutions.pose
mp_face_mesh = mp.solutions.face_mesh

NAME_POSE = [
    (PoseLandmark.NOSE), (PoseLandmark.LEFT_EYE_INNER),
    (PoseLandmark.LEFT_EYE), (PoseLandmark.LEFT_EYE_OUTER),
    (PoseLandmark.RIGHT_EYE_INNER), ( PoseLandmark.RIGHT_EYE),
    (PoseLandmark.RIGHT_EYE_OUTER), ( PoseLandmark.LEFT_EAR),
    (PoseLandmark.RIGHT_EAR), ( PoseLandmark.MOUTH_LEFT),
    (PoseLandmark.MOUTH_RIGHT), ( PoseLandmark.LEFT_SHOULDER),
    (PoseLandmark.RIGHT_SHOULDER), ( PoseLandmark.LEFT_ELBOW),
    (PoseLandmark.RIGHT_ELBOW), ( PoseLandmark.LEFT_WRIST),
    (PoseLandmark.RIGHT_WRIST), ( PoseLandmark.LEFT_PINKY),
    (PoseLandmark.RIGHT_PINKY), ( PoseLandmark.LEFT_INDEX),
    (PoseLandmark.RIGHT_INDEX), ( PoseLandmark.LEFT_THUMB),
    (PoseLandmark.RIGHT_THUMB), ( PoseLandmark.LEFT_HIP),
    (PoseLandmark.RIGHT_HIP), ( PoseLandmark.LEFT_KNEE),
    (PoseLandmark.RIGHT_KNEE), ( PoseLandmark.LEFT_ANKLE),
    (PoseLandmark.RIGHT_ANKLE), ( PoseLandmark.LEFT_HEEL),
    (PoseLandmark.RIGHT_HEEL), ( PoseLandmark.LEFT_FOOT_INDEX),
    (PoseLandmark.RIGHT_FOOT_INDEX)
]
class HolisticPublisher(Node):

    def __init__(self):
        super().__init__('mediapipe_publisher_holistic')
        self.publisher_ = self.create_publisher(MediaPipeHumanHolisticList, '/mediapipe/human_holistic_list', 10)
        # Compressed video, on the standard image_transport "<base_topic>/compressed"
        # naming convention (so image_transport tooling resolves it by convention)
        # even though this publishes CompressedImage directly rather than going
        # through the image_transport plugin machinery. JPEG quality 90 - high
        # enough to not wash out subtle skin-color detail (relevant for e.g. rPPG
        # reprocessing later), well short of raw. Path B (this node) has no other
        # way to get raw video into a bag; Path A (RealSense) already gets this for
        # free via realsense2_camera's own image_transport-based publishing, once
        # ros-jazzy-compressed-image-transport is installed - no code needed there.
        self.image_pub_ = self.create_publisher(CompressedImage, '/mediapipe/image_raw/compressed', 10)

        # Which camera to open: an index ("0", "1", ...) or a device path
        # ("/dev/video1"). Index 0 is not always the external webcam - check
        # with `v4l2-ctl --list-devices`.
        # dynamic_typing: `camera:=1` arrives as an int, `camera:=/dev/video1` as a string
        camera = str(self.declare_parameter(
            'camera', '0', ParameterDescriptor(dynamic_typing=True)).value)
        self.cap = cv2.VideoCapture(int(camera) if camera.isdigit() else camera)
        if not self.cap.isOpened():
            self.get_logger().error(f'Could not open camera {camera!r} - check '
                                    f'`v4l2-ctl --list-devices` and pass -p camera:=...')
            return
        # No resolution was ever requested here, so the driver picked its own
        # default (typically 640x480 on V4L2) - visibly low quality regardless of
        # JPEG settings downstream. 1280x720 @ 30fps chosen over the webcam's
        # max of 1920x1080 (confirmed via `v4l2-ctl --list-formats-ext`) as a
        # balance: a real quality jump without pushing MediaPipe Holistic's
        # per-frame CPU cost far enough to risk the actual achieved framerate
        # dropping below what's requested. Must set FOURCC to MJPG first - the
        # camera only offers 30fps at this resolution in MJPG (compressed at the
        # USB layer, decoded back to normal frames by OpenCV); the alternative
        # uncompressed YUYV format caps out well below 30fps at 1280x720.
        self.cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*'MJPG'))
        self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, 1280)
        self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 720)
        self.cap.set(cv2.CAP_PROP_FPS, 30)
        # Processing (~18.6 Hz) is slower than the camera (30 Hz), so with the
        # driver's default multi-frame queue read() returns frames that are
        # already several frames old, adding a variable lag to every timestamp.
        # A 1-frame buffer makes read() return the newest frame; the frames it
        # discards were going to be skipped anyway.
        self.cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
        self.get_logger().info(
            f"Camera {camera!r} opened at {int(self.cap.get(cv2.CAP_PROP_FRAME_WIDTH))}x"
            f"{int(self.cap.get(cv2.CAP_PROP_FRAME_HEIGHT))} @ "
            f"{self.cap.get(cv2.CAP_PROP_FPS)}fps, buffer "
            f"{int(self.cap.get(cv2.CAP_PROP_BUFFERSIZE))} (requested 1280x720@30, "
            f"buffer 1 - drivers can silently ignore .set(), this is what was "
            f"actually negotiated)")


    def getimage_callback(self):
        mediapipehumanholisticlist = MediaPipeHumanHolisticList() 
        mediapipehuman = MediaPipeHumanHand()
        points = HandPoint()
        drawing_spec = mp_drawing.DrawingSpec(thickness=1, circle_radius=1)
        with mp_face_mesh.FaceMesh(
            min_detection_confidence=0.5,
            min_tracking_confidence=0.5) as face_mesh,mp_hands.Hands(
                static_image_mode=False,
                min_detection_confidence=0.7,
                min_tracking_confidence=0.7,
                max_num_hands=2) as hands, mp_pose.Pose(
               min_detection_confidence=0.5,
               min_tracking_confidence=0.5) as pose:
            while self.cap.isOpened():

                success, image = self.cap.read()
                # Stamp at capture, not after the ~50 ms of MediaPipe
                # processing below, so the frame lines up with other streams.
                capture_stamp = self.get_clock().now().to_msg()
                if not success:
                    print("Sem camera.")
                    continue

                image = cv2.cvtColor(cv2.flip(image, 1), cv2.COLOR_BGR2RGB)
                image.flags.writeable = False
                results_face_mesh = face_mesh.process(image)
                results_pose = pose.process(image)
                results_hands= hands.process(image)
                image.flags.writeable = True
                image = cv2.cvtColor(image, cv2.COLOR_RGB2BGR)
                imageHeight, imageWidth, _ = image.shape

                # Publish the CLEAN frame (before any landmark overlays get drawn
                # onto `image` below) as compressed JPEG - publishing after the
                # draw_landmarks() calls further down would bake the skeleton/mesh
                # graphics into the recorded pixels, corrupting it for offline
                # reprocessing.
                encode_ok, encoded_image = cv2.imencode(
                    '.jpg', image, [int(cv2.IMWRITE_JPEG_QUALITY), 90])
                if encode_ok:
                    compressed_msg = CompressedImage()
                    compressed_msg.header.stamp = capture_stamp
                    compressed_msg.format = "jpeg"
                    compressed_msg.data = encoded_image.tobytes()
                    self.image_pub_.publish(compressed_msg)

                landmark_temp = []
                #face process
                if results_face_mesh.multi_face_landmarks:
                    index_face_mesh = 0
                    
                    while index_face_mesh <= 467:
                        
                        landmark_temp.append(results_face_mesh.multi_face_landmarks[0].landmark[index_face_mesh]) 
                        mediapipehumanholisticlist.human_face_mesh_list[index_face_mesh].x = results_face_mesh.multi_face_landmarks[0].landmark[index_face_mesh].x
                        mediapipehumanholisticlist.human_face_mesh_list[index_face_mesh].y = results_face_mesh.multi_face_landmarks[0].landmark[index_face_mesh].y
                        mediapipehumanholisticlist.human_face_mesh_list[index_face_mesh].z = results_face_mesh.multi_face_landmarks[0].landmark[index_face_mesh].z
                        index_face_mesh = index_face_mesh +1
                        
                
                    landmark_subset = landmark_pb2.NormalizedLandmarkList(landmark = landmark_temp)
                    mp_drawing.draw_landmarks(
                            image=image,
                            landmark_list=landmark_subset,
                            connections=mp_face_mesh.FACEMESH_TESSELATION,
                            landmark_drawing_spec=drawing_spec,
                            connection_drawing_spec=drawing_spec)
                else: # responsavel por mandar 0 nos topicos quando corpo nao esta na tela
                    index_pose = 0
                    for point in mp_pose.PoseLandmark:                          
                                                                                          
                        mediapipehumanholisticlist.human_pose_list[index_pose].name = str(NAME_POSE[index_pose])
                        mediapipehumanholisticlist.human_pose_list[index_pose].x = 0.0
                        mediapipehumanholisticlist.human_pose_list[index_pose].y = 0.0
                        mediapipehumanholisticlist.human_pose_list[index_pose].visibility = 0.0
                        index_pose = index_pose +1

                

                #processo pose
                # Draw the pose annotation on the image.
                mp_drawing.draw_landmarks(
                    image, results_pose.pose_landmarks, mp_pose.POSE_CONNECTIONS)
                if results_pose.pose_landmarks != None:
                    index_pose = 0
                    for pose_landmarks in (results_pose.pose_landmarks.landmark):
                        
                        mediapipehumanholisticlist.human_pose_list[index_pose].name = str(NAME_POSE[index_pose])
                        mediapipehumanholisticlist.human_pose_list[index_pose].x = pose_landmarks.x
                        mediapipehumanholisticlist.human_pose_list[index_pose].y = pose_landmarks.y
                        mediapipehumanholisticlist.human_pose_list[index_pose].visibility = pose_landmarks.visibility
                        index_pose = index_pose +1

                    mediapipehumanholisticlist.num_humans = 1
                    self.publisher_.publish(mediapipehumanholisticlist)
                else: # responsavel por mandar 0 nos topicos quando corpo nao esta na tela
                    index_pose = 0
                    for point in mp_pose.PoseLandmark:                          
                        print(index_pose)                                                                
                        mediapipehumanholisticlist.human_pose_list[index_pose].name = str(NAME_POSE[index_pose])
                        mediapipehumanholisticlist.human_pose_list[index_pose].x = 0.0
                        mediapipehumanholisticlist.human_pose_list[index_pose].y = 0.0
                        mediapipehumanholisticlist.human_pose_list[index_pose].visibility = 0.0
                        index_pose = index_pose +1

                #HAND PROCESS        
                
                if results_hands.multi_hand_landmarks != None:
                
                    hand_number_screen = 0 # index de controle de quantas maos aparecem na tela                  
                    #esse for passa pela quantidades de mão na tela setada como maximo 2 no momento
                    for hand_landmarks, handedness in zip(results_hands.multi_hand_landmarks,results_hands.multi_handedness):
                                            
                        if handedness.classification[0].label == "Right":
                            mp_drawing.draw_landmarks(
                            image, hand_landmarks, mp_hands.HAND_CONNECTIONS)
                            index_point = 0
                            
                            for point in mp_hands.HandLandmark:                                
                                normalizedLandmark = hand_landmarks.landmark[point]                                                                
                                mediapipehuman.right_hand_key_points[index_point].name = str(point) 
                                mediapipehuman.right_hand_key_points[index_point].x = normalizedLandmark.x
                                mediapipehuman.right_hand_key_points[index_point].y = normalizedLandmark.y
                                mediapipehuman.right_hand_key_points[index_point].z = normalizedLandmark.z                                
                                if hand_number_screen == 0:
                                    mediapipehuman.left_hand_key_points[index_point].name = str(point) 
                                    mediapipehuman.left_hand_key_points[index_point].x = 0.0
                                    mediapipehuman.left_hand_key_points[index_point].y = 0.0
                                    mediapipehuman.left_hand_key_points[index_point].z = 0.0
                                index_point = index_point +1
                            hand_number_screen = hand_number_screen +1

                        elif handedness.classification[0].label == "Left":
                            mp_drawing.draw_landmarks(
                            image, hand_landmarks, mp_hands.HAND_CONNECTIONS)
                            index_point = 0
                            
                            for point in mp_hands.HandLandmark:
                                
                                normalizedLandmark = hand_landmarks.landmark[point]  
                                points.name = str(point)                            
                                mediapipehuman.left_hand_key_points[index_point].name = str(point) 
                                mediapipehuman.left_hand_key_points[index_point].x = normalizedLandmark.x
                                mediapipehuman.left_hand_key_points[index_point].y = normalizedLandmark.y 
                                mediapipehuman.left_hand_key_points[index_point].z = normalizedLandmark.z
                                
                                if hand_number_screen == 0:
                                    mediapipehuman.right_hand_key_points[index_point].name = str(point) 
                                    mediapipehuman.right_hand_key_points[index_point].x = 0.0
                                    mediapipehuman.right_hand_key_points[index_point].y = 0.0
                                    mediapipehuman.right_hand_key_points[index_point].z = 0.0
                                index_point = index_point +1
                            hand_number_screen = hand_number_screen +1

                    
                else: # responsavel por mandar 0 nos topicos quando as duas maos nao estao na tela
                    index_point = 0
                    for point in mp_hands.HandLandmark:                          
                                                                                          
                        mediapipehuman.right_hand_key_points[index_point].name = str(point) 
                        mediapipehuman.right_hand_key_points[index_point].x = 0.0
                        mediapipehuman.right_hand_key_points[index_point].y = 0.0
                        mediapipehuman.right_hand_key_points[index_point].z = 0.0 
                        mediapipehuman.left_hand_key_points[index_point].name = str(point) 
                        mediapipehuman.left_hand_key_points[index_point].x = 0.0
                        mediapipehuman.left_hand_key_points[index_point].y = 0.0
                        mediapipehuman.left_hand_key_points[index_point].z = 0.0
                        index_point = index_point + 1 

                


                mediapipehumanholisticlist.human_hand_list.right_hand_key_points = mediapipehuman.right_hand_key_points
                mediapipehumanholisticlist.human_hand_list.left_hand_key_points = mediapipehuman.left_hand_key_points
                mediapipehumanholisticlist.num_humans = 1
                self.publisher_.publish(mediapipehumanholisticlist)
                cv2.imshow('MediaPipe Hands', image)
                if cv2.waitKey(5) & 0xFF == 27:
                    break        

def main(args=None):
    rclpy.init(args=args)
    start_audio()  # audio replaces the separate audio_recorder node

    holistic_publisher = HolisticPublisher()
    holistic_publisher.getimage_callback()

    holistic_publisher.cap.release()
    
    rclpy.spin(holistic_publisher)

    holistic_publisher.destroy_node()
    rclpy.shutdown()


if __name__ == '__main__':
    main()