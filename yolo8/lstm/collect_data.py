import cv2
import torch
import pickle
import time
import numpy as np
import os
from datetime import datetime
from collections import defaultdict
from ultralytics import YOLO

class DataCollector: 
    def __init__(self, video_path):
        self.video_path = video_path
        self.video = None
        # lambda: []는 새로운 키에 접근할 때마다 빈 리스트를 자동으로 생성
        self.feature_history = defaultdict(lambda: [])

        self.device = 'cuda' if torch.cuda.is_available() else 'cpu'
        print(f"Using device: {self.device}")

        self.model = YOLO('../weights/pose.pt')
        self.model.to(self.device)

    def initialize_video(self):
        self.video = cv2.VideoCapture(self.video_path)

        if not self.video.isOpened():
            raise RuntimeError(f'The video file cannot be opened: {self.video_path}')

        return self.video.isOpened()

    def calculate_features(self, keypoints):
        head, heart, tail = keypoints[:3]

        head_to_heart = np.array([heart[0] - head[0], heart[1] - head[1]])
        heart_to_tail = np.array([tail[0] - heart[0], tail[1] - heart[1]])

        mean_direction = (head_to_heart + heart_to_tail) / 2
        body_orientation = float(np.degrees(np.arctan2(mean_direction[1], mean_direction[0])))
    
        # body_orientation 테스트중
        features = {
            'head_x': float(head[0]),
            'head_y': float(head[1]),
            'heart_x': float(heart[0]),
            'heart_y': float(heart[1]),
            'body_orientation': body_orientation,
            'timestamp': time.time()
        }
    
        return features

    def collect_data(self): 
        if not self.initialize_video():
            print('Video initialization failed')
            return

        total_frames = int(self.video.get(cv2.CAP_PROP_FRAME_COUNT))
        processed_frames = 0
        prev_features = {}
        # 100ms 이상 차이나는 프레임은 속도 계산 제외
        max_time_gap = 0.1

        try:
            while True:
                ret, frame = self.video.read()
                if not ret:
                    break

                with torch.no_grad():
                    results = self.model.track(
                        source=frame,
                        tracker="botsort.yaml",
                        conf=0.2,
                        iou=0.2,
                        persist=True,
                    )

                result = results[0]

                if result.boxes.id is not None and result.keypoints is not None:
                    boxes = result.boxes.xywh.cpu()
                    track_ids = result.boxes.id.int().cpu().tolist()
                    keypoints = result.keypoints.data.cpu().numpy()
                    confidences = result.boxes.conf.cpu()

                    if len(track_ids) > 0:
                        max_conf_idx = confidences.argmax()
                        kpts = keypoints[max_conf_idx]
                        fixed_track_id = 0

                        features = self.calculate_features(kpts)

                        if fixed_track_id in prev_features:
                            prev = prev_features[fixed_track_id]
                            time_diff = features['timestamp'] - prev['timestamp']

                            if time_diff <= max_time_gap:
                                features.update({
                                    'velocity_x': (features['heart_x'] - prev['heart_x']) / time_diff,
                                    'velocity_y': (features['heart_y'] - prev['heart_y']) / time_diff,
                                    'angular_velocity': (features['body_orientation'] - prev['body_orientation']) / time_diff
                                })
                            else: 
                                features.update({
                                    'velocity_x': 0,
                                    'velocity_y': 0,
                                    'angular_velocity': 0
                                })
                        else:
                            features.update({
                                'velocity_x': 0,
                                'velocity_y': 0,
                                'angular_velocity': 0
                            })
                        
                        prev_features[fixed_track_id] = features
                        self.feature_history[fixed_track_id].append(features)

                processed_frames += 1
                progress = (processed_frames / total_frames) * 100
                print(f'\rProcessing... {processed_frames}/{total_frames} frames '
                    f'({progress:.1f}%) Processed, Number of features collected: {len(self.feature_history[0])}', 
                    end='')

                annotated_frame = result.plot()
                cv2.imshow('Data Collection', annotated_frame)
            
                if cv2.waitKey(1) & 0xFF == ord('q'):
                    break
        except KeyboardInterrupt:
            print("\nStopped by user")
        finally:
            self.save_data()
            self.cleanup()

    def save_data(self):
        os.makedirs('collected_data', exist_ok=True)
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        filename = f'collected_data/features_{timestamp}.pkl'
        
        with open(filename, 'wb') as f:
            pickle.dump(dict(self.feature_history), f)

        total_frames = len(self.feature_history[0]) if 0 in self.feature_history else 0
        
        print(f"\nData has been saved: {filename}")
        print(f"Number of tracked frames: {total_frames}")

    def cleanup(self):
        if self.video is not None:
            self.video.release()
            cv2.destroyAllWindows()

if __name__ == "__main__":
    video_path = "../../resource/giant.mp4" 
    collector = DataCollector(video_path)
    collector.collect_data()


