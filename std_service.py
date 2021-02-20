import RobotRaconteur as RR
RRN=RR.RobotRaconteurNode.s
import RobotRaconteurCompanion as RRC
import numpy as np
import traceback, os, cv2, time, threading
import pyrealsense2 as rs
from RobotRaconteurCompanion.Util.SensorDataUtil import SensorDataUtil


class RGB_Cam(object):
	def __init__(self):
		self._streaming = False
		self._capture_lock = threading.Lock()

	def start_streaming(self):
		self._streaming=True


	def stop_streaming(self):
		self._streaming=False

class Depth_Cam(object):
	def __init__(self):
		self._streaming = False
		self._capture_lock = threading.Lock()

	def start_streaming(self):
		self._streaming=True


	def stop_streaming(self):
		self._streaming=False

class Multi_Cam(object):
	def __init__(self):
		self._streaming = False
		self._capture_lock = threading.Lock()
		self.RGB_Cam_obj=RGB_Cam()
		self.Depth_Cam_obj=Depth_Cam()
		self.cameras=[self.RGB_Cam_obj,self.Depth_Cam_obj]
		self._image_consts = RRN.GetConstants('com.robotraconteur.image')
		self._image_type = RRN.GetStructureType('com.robotraconteur.image.Image')
		self._depth_image_type = RRN.GetStructureType('com.robotraconteur.image.DepthImage')
		self._image_info_type = RRN.GetStructureType('com.robotraconteur.image.ImageInfo')
		
	def get_cameras(self,ind):
		int_ind=int(ind)
		return self.cameras[int_ind], "com.robotraconteur.imaging.Camera"
	def _cv_mat_to_image(self, mat):

		is_mono = False
		if (len(mat.shape) == 2 or mat.shape[2] == 1):
			is_mono = True

		image_info = self._image_info_type()
		image_info.width =mat.shape[1]
		image_info.height = mat.shape[0]
		if is_mono:
			image_info.step = mat.shape[1]
			image_info.encoding = self._image_consts["ImageEncoding"]["mono8"]
		else:
			image_info.step = mat.shape[1]*3
			image_info.encoding = self._image_consts["ImageEncoding"]["rgb8"]

		image = self._image_type()
		image.image_info = image_info
		image.data=mat.reshape(mat.size, order='C')
		return image

	def _mat_to_depthimage(self, mat):
		image = self._depth_image_type()
		image.depth_image=self._cv_mat_to_image(mat)
		image.depth_ticks_per_meter=1./self.depth_scale
		return image


class PC_Sensor(object):
	def __init__(self):
		self.active=True
		self._point_type = RRN.GetNamedArrayDType("com.robotraconteur.geometryf.Point")
		self._pointcloud_type = RRN.GetStructureType('com.robotraconteur.pointcloud.PointCloudf')
		self._pointcloudsensordata_type=RRN.GetStructureType('com.robotraconteur.pointcloud.sensor.PointCloudSensorData')

	def _pc_to_RRpc(self,verts,texcoords,w,h):
		RRpc=self._pointcloud_type()
		RRpc.width=w
		RRpc.height=h
		RRpc.points=np.zeros((len(verts)),dtype=self._point_type)

		for i in range(len(verts)):
			RRpc.points[i]['x']=verts[i][0]
			RRpc.points[i]['y']=verts[i][1]
			RRpc.points[i]['z']=verts[i][2]
		return RRpc
	def _RRpc_to_PCSD(self,RRpc):
		PCSD=self._pointcloudsensordata_type()
		PCSD.point_cloud=RRpc
		return PCSD

class RSImpl(object):
	#Issue: Officially we currently only support 640x480/1024x768 for Depth and 1920x1080/1280x720 for Color.
	def __init__(self, width=640, height=480, fps=30, camera_info=None):
		#initialize RR obj
		self.Multi_Cam_obj=Multi_Cam()
		self.PC_Sensor=PC_Sensor()

		# Create a pipeline
		self.pipeline = rs.pipeline()

		#Create a config and configure the pipeline to stream
		#  different resolutions of color and depth streams
		self.config = rs.config()
		self.config.enable_stream(rs.stream.depth, width, height, rs.format.z16, fps)
		self.config.enable_stream(rs.stream.color, width, height, rs.format.bgr8, fps)

		# Start streaming
		self.profile = self.pipeline.start(self.config)

		# Getting the depth sensor's depth scale (see rs-align example for explanation)
		self.depth_sensor = self.profile.get_device().first_depth_sensor()
		self.depth_scale = self.depth_sensor.get_depth_scale()
		print("Depth Scale is: " , self.depth_scale)

		# Create an align object
		# rs.align allows us to perform alignment of depth frames to others frames
		# The "align_to" is the stream type to which we plan to align depth frames.
		align_to = rs.stream.color
		self.align = rs.align(align_to)

		# Point cloud
		self.pc = rs.pointcloud()
		self.decimate = rs.decimation_filter()
		self.decimate.set_option(rs.option.filter_magnitude, 2 ** 1)


		
		self._capture_lock = threading.Lock()
		

		self._streaming = False

	

	def frame_threadfunc(self):
		while(self._streaming):
			with self._capture_lock:
				try:
					# Get frameset of color and depth
					frames = self.pipeline.wait_for_frames()
					# frames.get_depth_frame() is a 640x360 depth image

					# Align the depth frame to color frame
					aligned_frames = self.align.process(frames)

					# Get aligned frames
					aligned_depth_frame = aligned_frames.get_depth_frame() # aligned_depth_frame is a 640x480 depth image
					color_frame = aligned_frames.get_color_frame()

					# Validate that both frames are valid
					if not aligned_depth_frame or not color_frame:
						continue

					depth_image = np.asanyarray(aligned_depth_frame.get_data())
					depth_colormap = cv2.applyColorMap(cv2.convertScaleAbs(depth_image, alpha=0.03), cv2.COLORMAP_JET)
					color_image = np.asanyarray(color_frame.get_data(),dtype=np.uint8)
					#depth data matching with image
					depth_data= np.asarray(aligned_depth_frame.as_frame().get_data())

					if self.Multi_Cam_obj.cameras[0]._streaming:				
						self.Multi_Cam_obj.cameras[0].frame_stream.SendPacket(self.Multi_Cam_obj._cv_mat_to_image(color_image))
					if self.Multi_Cam_obj.cameras[1]._streaming:
						self.Multi_Cam_obj.cameras[1].frame_stream.SendPacket(self.Multi_Cam_obj._cv_mat_to_image(depth_colormap))
					###pointcloud part
					depth_frame = self.decimate.process(aligned_depth_frame)

					# Grab new intrinsics (may be changed by decimation)
					depth_intrinsics = rs.video_stream_profile(
						depth_frame.profile).get_intrinsics()
					w, h = depth_intrinsics.width, depth_intrinsics.height

					points = self.pc.calculate(depth_frame)
					self.pc.map_to(color_frame)

					# Pointcloud data to arrays
					v, t = points.get_vertices(), points.get_texture_coordinates()
					verts = np.asanyarray(v).view(np.float32).reshape(-1, 3)  # xyz
					texcoords = np.asanyarray(t).view(np.float32).reshape(-1, 2)  # uv

					PCSD=self.PC_Sensor._RRpc_to_PCSD(self.PC_Sensor._pc_to_RRpc(verts,texcoords,w,h))
					self.PC_Sensor.point_cloud_sensor_data.SendPacket(PCSD)
				except:
					traceback.print_exc()



	def start_streaming(self):
		if (self._streaming):
			raise RR.InvalidOperationException("Already streaming")
		self._streaming=True
		t=threading.Thread(target=self.frame_threadfunc)
		t.start()

	def stop_streaming(self):
		if (not self._streaming):
			raise RR.InvalidOperationException("Not streaming")
		self._streaming=False


def main():
	with RR.ServerNodeSetup("RS_Node", 25415) as node_setup:
		#RR setup
		RRC. RegisterStdRobDefServiceTypes(RRN)
		#register service file and service
		RRN.RegisterServiceTypeFromFile("robdef/edu.rpi.robotics.realsense.robdef")


		RS_obj=RSImpl()

		RS_obj.start_streaming()

		RRN.RegisterService("Multi_Cam_Service","com.robotraconteur.imaging.MultiCamera",RS_obj.Multi_Cam_obj)
		RRN.RegisterService("PC_Service","com.robotraconteur.pointcloud.sensor.PointCloudSensor",RS_obj.PC_Sensor)

		input("Press enter to quit")

		RS_obj.stop_streaming()
		RS_obj.pipeline.stop()




if __name__ == "__main__":
	main()