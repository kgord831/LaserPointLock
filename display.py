# TODO: stop using global vars and put this code into a fucking window

if __name__ == "__main__":
    import sys
    import usb
    import visa
    import time
    import numpy as np
    import pyqtgraph as pg
    from pointing_ui import Ui_MainWindow
    from PyQt5 import QtCore, QtGui, QtWidgets
    from camera import MightexCamera
    from camera import FakeCamera
    from motors import MDT693A_Motor, FakeMotor

    STATE_MEASURE = 0
    STATE_CALIBRATE = 1
    STATE_LOCKED = 2
    state = STATE_MEASURE
    previous_state = STATE_MEASURE
    state_change = 0

    pg.setConfigOptions(imageAxisOrder='row-major')
    pg.setConfigOption('background', 'w')
    pg.setConfigOption('foreground', 'k')

    UPDATE_TIME = 2000  # ms

    app = QtWidgets.QApplication(sys.argv)
    MainWindow = QtWidgets.QMainWindow()
    ui = Ui_MainWindow()
    ui.setupUi(MainWindow)
    cam_model = QtGui.QStandardItemModel()
    motor_model = QtGui.QStandardItemModel()
    error_dialog = QtWidgets.QErrorMessage()

    # Find the cameras
    cam_dev_list = list(usb.core.find(find_all=True, idVendor=0x04B4))
    cam_list = []
    if len(cam_dev_list) == 0:
        print('Could not find any Mightex cameras!')
    else:
        for i, cam in enumerate(cam_dev_list):
            c = MightexCamera(dev=cam)
            cam_list.append(c)
            cam_model.appendRow(QtGui.QStandardItem(c.serial_no))
    # Find motors using VISA
    resourceManager = visa.ResourceManager()
    for dev in resourceManager.list_resources():
        motor_model.appendRow(QtGui.QStandardItem(str(dev)))
    motor_list = []
    # Add fake cameras
    for i in range(3):
        c = FakeCamera()
        cam_list.append(c)
        cam_model.appendRow(QtGui.QStandardItem(c.serial_no))
    # Set models and default values for combo boxes
    ui.cb_cam1.setModel(cam_model)
    ui.cb_cam2.setModel(cam_model)
    ui.cb_motors_1.setModel(motor_model)
    ui.cb_motors_2.setModel(motor_model)
    if len(resourceManager.list_resources()) > 1:
        ui.cb_motors_1.setCurrentIndex(0)
        ui.cb_motors_2.setCurrentIndex(1)
    else:
        ui.cb_motors_1.setCurrentIndex(-1)
        ui.cb_motors_1.setCurrentIndex(-1)
    # Initialize global variables for tracking pointing
    cam1_x = np.ndarray(0)
    cam1_y = np.ndarray(0)
    cam2_x = np.ndarray(0)
    cam2_y = np.ndarray(0)
    cam1_x_time = np.ndarray(0)
    cam1_y_time = np.ndarray(0)
    cam2_x_time = np.ndarray(0)
    cam2_y_time = np.ndarray(0)
    cam1_x_plot = ui.gv_cam_xy.addPlot(row=0, col=0, labels={'left': 'Cam 1 X'}).plot()
    cam1_y_plot = ui.gv_cam_xy.addPlot(row=1, col=0, labels={'left': 'Cam 1 Y'}).plot()
    cam2_x_plot = ui.gv_cam_xy.addPlot(row=2, col=0, labels={'left': 'Cam 2 X'}).plot()
    cam2_y_plot = ui.gv_cam_xy.addPlot(row=3, col=0, labels={'left': 'Cam 2 Y'}).plot()
    # Initialize global variables for piezo motor voltages
    motor1_x = np.ndarray(0)
    motor1_y = np.ndarray(0)
    motor2_x = np.ndarray(0)
    motor2_y = np.ndarray(0)
    motor1_x_plot = ui.gv_piezo.addPlot(row=0, col=0).plot()
    motor1_y_plot = ui.gv_piezo.addPlot(row=1, col=0).plot()
    motor2_x_plot = ui.gv_piezo.addPlot(row=2, col=0).plot()
    motor2_y_plot = ui.gv_piezo.addPlot(row=3, col=0).plot()

    ## Set a custom color map
    colors = [
        (68, 1, 84),
        (72, 33, 115),
        (67, 62, 133),
        (56, 88, 140),
        (45, 112, 142),
        (37, 133, 142),
        (30, 155, 138),
        (42, 176, 127),
        (82, 197, 105),
        (134, 213, 73),
        (194, 223, 35),
        (253, 231, 37)
    ]
    cmap = pg.ColorMap(pos=np.linspace(0.0, 1.0, 12), color=colors)
    ui.gv_camera1.setColorMap(cmap)
    ui.gv_camera2.setColorMap(cmap)
    # Set the com guide lines
    cam1_x_line = pg.InfiniteLine(movable=False, angle=0)
    cam1_y_line = pg.InfiniteLine(movable=False, angle=90)
    cam2_x_line = pg.InfiniteLine(movable=False, angle=0)
    cam2_y_line = pg.InfiniteLine(movable=False, angle=90)
    ui.gv_camera1.addItem(cam1_x_line)
    ui.gv_camera1.addItem(cam1_y_line)
    ui.gv_camera2.getView().addItem(cam2_x_line)
    ui.gv_camera2.getView().addItem(cam2_y_line)
    cam_lines = [cam1_x_line, cam1_y_line, cam2_x_line, cam2_y_line]
    for l in cam_lines:
        l.setVisible(False)

    # Initialize global variables
    cam1_index = -1
    cam2_index = -1
    cam1_threshold = 0
    cam2_threshold = 0
    cam1_reset = True
    cam2_reset = True
    num_out_of_voltage_range = 0

    # Initialize global variables for Locking
    LockTimeStart = 0
    TimeLastUnlock = 0

    saturated_cam1 = False
    under_saturated_cam1 = False
    saturated_cam2 = False
    under_saturated_cam2 = False

    # Initialize global variables for calibration
    calib_index = 0
    reset_piezo = 0
    override = False
    calibration_voltages = 10 * np.arange(15)+5
    mot1_x_voltage, mot1_y_voltage, mot2_x_voltage, mot2_y_voltage = np.empty((4, len(calibration_voltages)))
    mot1_x_cam1_x, mot1_x_cam1_y, mot1_x_cam2_x, mot1_x_cam2_y = np.empty((4, len(calibration_voltages)))
    mot1_y_cam1_x, mot1_y_cam1_y, mot1_y_cam2_x, mot1_y_cam2_y = np.empty((4, len(calibration_voltages)))
    mot2_x_cam1_x, mot2_x_cam1_y, mot2_x_cam2_x, mot2_x_cam2_y = np.empty((4, len(calibration_voltages)))
    mot2_y_cam1_x, mot2_y_cam1_y, mot2_y_cam2_x, mot2_y_cam2_y = np.empty((4, len(calibration_voltages)))
    starting_v = 75.0*np.ones(4)
    calib_mat = np.array([[1, 0, 0, 0], [0, 1, 0, 0], [0, 0, 1, 0], [0, 0, 0, 1]])

    def resetHist(ref, min=0, max=255):
        """
        Given a reference to an image view, set the histogram's range and levels to min and max
        """
        assert isinstance(ref, pg.ImageView)
        ref.getHistogramWidget().setHistogramRange(min, max)
        ref.getHistogramWidget().setLevels(min, max)

    def addToPlot(data, plot, point, maxSize=100):
        """
        Scrolling plot with a maximum size
        """
        if (data.size < maxSize):
            data = np.append(data, point)
        else:
            data = np.roll(data, -1)
            data[-1] = point
            data = np.roll(data, -1)
            data[-1] = point
        plot.setData(data)
        return data

    def calc_com_x(img):
        Nx, Ny = img.shape
        x = np.arange(Nx)
        y = np.arange(Ny)
        X, _ = np.meshgrid(x, y, indexing='ij')
        w = img/np.sum(img)
        com_x = np.sum(X*w)
        return com_x

    def calc_com_y(img):
        Nx, Ny = img.shape
        x = np.arange(Nx)
        y = np.arange(Ny)
        _, Y = np.meshgrid(x, y, indexing='ij')
        w = img/np.sum(img)
        com_y = np.sum(Y*w)
        return com_y

    def calc_com(img):
        """
        Given an image, img, calculate the center of mass in pixel coordinates
        """
        Nx, Ny = img.shape
        x = np.arange(Nx)
        y = np.arange(Ny)
        X, Y = np.meshgrid(x, y, indexing='ij')
        try:
            w = img/np.sum(img)
        except RuntimeWarning:
            pass
        com_x = np.sum(X*w)
        com_y = np.sum(Y*w)
        return com_x, com_y

    def calc_com_opt(img):
        """Given an img, calculate the com in pixel coordinates. Algorithm slightly
        optimized by 1) calculating the maximum, 2) estimating the width by finding 
        the max/4 position, and 3) cropping the window to the max/4 position and
        calculating com
        """
        i, j = np.unravel_index(np.argmax(img), img.shape)
        r = np.abs(i - np.argmin(np.abs(img[i, j]/4 - img[:, j])))
        start_i = max(0, i - r)
        end_i = min(img.shape[0] - 1, i + r)
        start_j = max(0, j - r)
        end_j = min(img.shape[1] - 1, j + r)
        com_x, com_y = calc_com(img[start_i:end_i, start_j:end_j])
        return com_x + start_i, com_y + start_j

    def update():
        global previous_state, state_change, LockTimeStart
        start_time = time.time()
        if state - previous_state == 0:
            state_change = False
        else:
            state_change = True
        previous_state = state
        msg = ''
        if state == STATE_MEASURE:
            updateMeasure()
            msg += 'UNLOCKED'
        elif state == STATE_CALIBRATE:
            updateCalibrate()
            msg += 'Calibrating...'
        elif state == STATE_LOCKED:
            if state_change:
                LockTimeStart = time.monotonic()
            updateLocked()
            msg += 'LOCKED'
        else:
            msg += 'ERROR'
        ui.statusbar.showMessage('{0}\tUpdate time: {1:.3f} (s)'.format(msg, time.time() - start_time))

    # TODO: make it possible to set avg_frames and avg_com through the GUI.
    def take_img_calibration(cam_index, cam_view=0, threshold=0, avg_frames=1, avg_com=1):
        global state
        global cam1_x, cam2_x, cam1_y, cam2_y
        global cam1_x_line, cam2_x_line, cam1_y_line, cam2_y_line
        # Get a com that is an average over the number of avg_com
        if avg_com<2:
            # Get an image that is an average over the number of AvgFrames
            if avg_frames<2:
                try:
                    img = cam_list[cam_index].get_frame()
                except RuntimeError:
                    state = STATE_MEASURE
                    img = np.array([1])
            else:
                for i in range(avg_frames):
                    try:
                        temp_img = cam_list[cam_index].get_frame()
                    except RuntimeError:
                        state = STATE_MEASURE
                        temp_img = np.array([1])
                        img = np.array([1])
                    if i==0:
                        img = temp_img
                    else:
                        img += temp_img
                img = img/avg_frames
            if threshold > 0:
                img[img < threshold*avg_frames] = 0
            if cam_view == 0:
                ui.le_cam1_max.setText(str(np.max(img/avg_frames))) #Just updates the GUI to say what the max value of the camera is
            else:
                ui.le_cam2_max.setText(str(np.max(img/avg_frames))) #Just updates the GUI to say what the max value of the camera is
            com = calc_com(img)  # Grab COM
        else:
            for j in range(avg_com):
                # Get an image that is an average over the number of AvgFrames
                if avg_frames < 2:
                    try:
                        img = cam_list[cam_index].get_frame()
                    except RuntimeError:
                        state = STATE_MEASURE
                        img = np.array([1])
                else:
                    for i in range(avg_frames):
                        try:
                            temp_img = cam_list[cam_index].get_frame()
                        except RuntimeError:
                            state = STATE_MEASURE
                            temp_img = np.array([1])
                            img = np.array([1])
                        if i == 0:
                            img = temp_img
                        else:
                            img += temp_img
                    img = img / avg_frames
                if threshold > 0:
                    img[img < threshold * avg_frames] = 0
                if cam_view == 0:
                    ui.le_cam1_max.setText(str(
                        np.max(img / avg_frames)))  # Just updates the GUI to say what the max value of the camera is
                else:
                    ui.le_cam2_max.setText(str(
                        np.max(img / avg_frames)))  # Just updates the GUI to say what the max value of the camera is
                temp_com = calc_com(img)  # Grab COM
                if j == 0:
                    com = temp_com
                else:
                    com += temp_com

        # The below just plots the last 100 points of the COM for x and y
        if cam_view == 0:  # Decide whether cam 0 or 1, which camera?
            #x
            cam1_x_line.setPos(com[0])
            cam1_x_line.setVisible(True)
            if (cam1_x.size < 100):
                cam1_x = np.append(cam1_x, com[0])
            else:
                cam1_x = np.roll(cam1_x, -1)
                cam1_x[-1] = com[0]
            cam1_x_plot.setData(cam1_x)
            #y
            cam1_y_line.setPos(com[1])
            cam1_y_line.setVisible(True)
            if (cam1_y.size < 100):
                cam1_y = np.append(cam1_y, com[1])
            else:
                cam1_y = np.roll(cam1_y, -1)
                cam1_y[-1] = com[1]
            cam1_y_plot.setData(cam1_y)
        # Last 100 points of COM have been plotted, removing old points to maintain just 100.
        # Ditto the above for camera 2 below
        else:
            #x
            cam2_x_line.setPos(com[0])
            cam2_x_line.setVisible(True)
            if (cam2_x.size < 100):
                cam2_x = np.append(cam2_x, com[0])
            else:
                cam2_x = np.roll(cam2_x, -1)
                cam2_x[-1] = com[0]
            cam2_x_plot.setData(cam2_x)
            # y
            cam2_y_line.setPos(com[1])
            cam2_y_line.setVisible(True)
            if (cam2_y.size < 100):
                cam2_y = np.append(cam2_y, com[1])
            else:
                cam2_y = np.roll(cam2_y, -1)
                cam2_y[-1] = com[1]
            cam2_y_plot.setData(cam2_y)
        return img, com


    def take_img(cam_index, cam_view=0, threshold=0, resetView=False, avg_frames=2, avg_com=2):
        """
        Given the camera at cam_index in the camera list
        Update cam_view with its image and COM
        Use threshold to zero out values below threshold
        Return if the image is saturated
        """
        global cam1_x_line, cam1_y_line, cam1_x, cam1_y
        global cam2_x_line, cam2_y_line, cam2_x, cam2_y
        global cam1_x, cam1_y, cam2_x, cam2_y
        global cam1_x_plot, cam1_y_plot, cam2_x_plot, cam2_y_plot
        assert cam_index >= 0
        assert cam_view == 0 or cam_view == 1

        if avg_com < 2:
            # Get an image that is an average over the number of AvgFrames
            if avg_frames < 2:
                try:
                    img = cam_list[cam_index].get_frame()
                except RuntimeError:
                    state = STATE_MEASURE
                    img = np.array([1])
            else:
                for i in range(avg_frames):
                    try:
                        temp_img = cam_list[cam_index].get_frame()
                    except RuntimeError:
                        state = STATE_MEASURE
                        temp_img = np.array([1])
                        img = np.array([1])
                    if i==0:
                        img = temp_img
                    else:
                        img += temp_img
                img = img/avg_frames
            if threshold > 0:
                img[img < threshold*avg_frames] = 0
            if cam_view == 0:
                ui.le_cam1_max.setText(str(np.max(img/avg_frames))) #Just updates the GUI to say what the max value of the camera is
            else:
                ui.le_cam2_max.setText(str(np.max(img/avg_frames))) #Just updates the GUI to say what the max value of the camera is
            com = calc_com(img)  # Grab COM
        else:
            for j in range(avg_com):
                # Get an image that is an average over the number of AvgFrames
                if avg_frames < 2:
                    try:
                        img = cam_list[cam_index].get_frame()
                    except RuntimeError:
                        state = STATE_MEASURE
                        img = np.array([1])
                else:
                    for i in range(avg_frames):
                        try:
                            temp_img = cam_list[cam_index].get_frame()
                        except RuntimeError:
                            state = STATE_MEASURE
                            temp_img = np.array([1])
                            img = np.array([1])
                        if i == 0:
                            img = temp_img
                        else:
                            img += temp_img
                    img = img / avg_frames
                if threshold > 0:
                    img[img < threshold * avg_frames] = 0
                if cam_view == 0:
                    ui.le_cam1_max.setText(str(
                        np.max(img / avg_frames)))  # Just updates the GUI to say what the max value of the camera is
                else:
                    ui.le_cam2_max.setText(str(
                        np.max(img / avg_frames)))  # Just updates the GUI to say what the max value of the camera is
                temp_com = calc_com(img)  # Grab COM
                if j == 0:
                    com = temp_com
                else:
                    com += temp_com
        under_saturated = np.all(img < 50)
        saturated = np.any(img > 250)
        if cam_view == 0:
            ui.le_cam1_max.setText(str(np.max(img)))
            cam_x_line = cam1_x_line
            cam_y_line = cam1_y_line
            cam_x_data = cam1_x
            cam_y_data = cam1_y
            cam_x_plot = cam1_x_plot
            cam_y_plot = cam1_y_plot
            gv_camera = ui.gv_camera1
        else:
            ui.le_cam2_max.setText(str(np.max(img)))
            cam_x_line = cam2_x_line
            cam_y_line = cam2_y_line
            cam_x_data = cam2_x
            cam_y_data = cam2_y
            cam_x_plot = cam2_x_plot
            cam_y_plot = cam2_y_plot
            gv_camera = ui.gv_camera2
        # Calculate COM
        # TODO: optimize COM calculation by slicing window near
        # the max value
        com_x = com[0]
        com_y = com[1]
        cam_x_line.setPos(com_x)
        cam_y_line.setPos(com_y)
        cam_x_line.setVisible(True)
        cam_y_line.setVisible(True)
        if (cam_x_data.size < 100):
            cam_x_data = np.append(cam_x_data, com_x)
            cam_y_data = np.append(cam_y_data, com_y)
        else:
            cam_x_data = np.roll(cam_x_data, -1)
            cam_x_data[-1] = com_x
            cam_y_data = np.roll(cam_y_data, -1)
            cam_y_data[-1] = com_y
        if cam_view == 0:
            cam1_x = cam_x_data
            cam1_y = cam_y_data
        else:
            cam2_x = cam_x_data
            cam2_y = cam_y_data
        cam_x_plot.setData(cam_x_data)
        cam_y_plot.setData(cam_y_data)
        if resetView:
            gv_camera.setImage(img, autoRange=True, autoLevels=False, autoHistogramRange=False)
        else:
            gv_camera.setImage(img, autoRange=False, autoLevels=False, autoHistogramRange=False)
        return img, com_x, com_y, under_saturated, saturated


    def updateCalibrate():
        global state, calib_index, cam1_threshold, cam2_threshold
        global cam1_index, cam2_index
        global calibration_voltages, starting_v
        global calib_mat
        global override
        global mot1_x_voltage, mot1_y_voltage, mot2_x_voltage, mot2_y_voltage
        # mot represents the motor number, which is 1 or 2
        # cam represents the camera we're looking at, which is either near or far
        # x or y represents whether we are looking at the horizontal or vertical
        global mot1_x_cam1_x, mot1_x_cam1_y, mot1_x_cam2_x, mot1_x_cam2_y
        global mot1_y_cam1_x, mot1_y_cam1_y, mot1_y_cam2_x, mot1_y_cam2_y
        global mot2_x_cam1_x, mot2_x_cam1_y, mot2_x_cam2_x, mot2_x_cam2_y
        global mot2_y_cam1_x, mot2_y_cam1_y, mot2_y_cam2_x, mot2_y_cam2_y
        global motor_list
        global motor1_x, motor1_y, motor2_x, motor2_y
        global motor1_x_plot, motor1_y_plot, motor2_x_plot, motor2_y_plot
        global reset_piezo  #Switch variable.
        if (ui.cb_motors_1.currentIndex() < 0):
            error_dialog.showMessage('You need to select Motor 1.')
            state = STATE_MEASURE
            return
        elif (ui.cb_motors_2.currentIndex() < 0):
            error_dialog.showMessage('You need to select Motor 2.')
            state = STATE_MEASURE
            return
        elif ui.cb_motors_1.currentIndex() == ui.cb_motors_2.currentIndex():
            error_dialog.showMessage('You need to select two unique motors.')
            state = STATE_MEASURE
            return
        if cam1_index < 0:
            error_dialog.showMessage('You need to select camera 1.')
            state = STATE_MEASURE
            return
        elif cam2_index < 0:
            error_dialog.showMessage('You need to select camera 2.')
            state = STATE_MEASURE
            return
        elif cam1_index == cam2_index:
            error_dialog.showMessage('You need to select two different cameras.')
            state = STATE_MEASURE
            return
        else:
            num_steps_per_motor = len(calibration_voltages)
            if calib_index < num_steps_per_motor * 4:
                motor_index = calib_index // num_steps_per_motor
                voltage_step = calib_index % num_steps_per_motor
                set_voltage = calibration_voltages[voltage_step]
                if motor_index == 0:
                    # first motor, channel 1
                    voltage = motor_list[0].ch1_v
                    if (abs(voltage - set_voltage) < 0.2 or override):
                        time.sleep(0.2) #Give time between setting the piezo and measuring the COM
                        override = False
                        reset_piezo = 0
                        # update motor voltages
                        motor1_x = addToPlot(motor1_x, motor1_x_plot, voltage)
                        # get a frame from cam1 for x motor
                        img, com = take_img_calibration(cam1_index, cam_view = 0, threshold = cam1_threshold, avg_frames = 2, avg_com = 2) #ToDo: set avg_.. with GUI
                        # put in list, update image
                        mot1_x_cam1_x[voltage_step] = com[0]
                        mot1_x_cam1_y[voltage_step] = com[1]
                        ui.gv_camera1.setImage(img, autoRange=False, autoLevels=False, autoHistogramRange=False)
                        # get a frame from cam2 for x motor
                        img, com = take_img_calibration(cam2_index, cam_view=1, threshold = cam2_threshold, avg_frames = 2, avg_com = 2)
                        # put in list
                        mot1_x_cam2_x[voltage_step] = com[0]
                        mot1_x_cam2_y[voltage_step] = com[1]
                        ui.gv_camera2.setImage(img, autoRange=False, autoLevels=False, autoHistogramRange=False)
                        # And save a list of the actual voltages
                        mot1_x_voltage[voltage_step] = voltage
                        # next step of calibration
                        calib_index += 1
                    else:
                        #If the voltage is not where it should be, update it.
                        motor_list[0].ch1_v = set_voltage
                        if reset_piezo > 0: # Fuck it overide the tolerance, because now the code is improved to store the actual voltage
                            override = True
                        reset_piezo += 1
                elif motor_index == 1:
                    motor_list[0].ch1_v = starting_v[0]
                    # first motor, channel 2
                    voltage = motor_list[0].ch2_v
                    if (abs(voltage - set_voltage) < 0.2 or override):
                        time.sleep(0.2) #Give time between setting the piezo and measuring the COM
                        override = False
                        reset_piezo = 0
                        # update motor voltages
                        motor1_y = addToPlot(motor1_y, motor1_y_plot, voltage)
                        # get a frame from cam1
                        img, com = take_img_calibration(cam1_index, cam_view = 0, threshold = cam1_threshold, avg_frames = 2, avg_com = 2)
                        # put in list
                        mot1_y_cam1_x[voltage_step] = com[0]
                        mot1_y_cam1_y[voltage_step] = com[1]
                        ui.gv_camera1.setImage(img, autoRange=False, autoLevels=False, autoHistogramRange=False)
                        # get a frame from cam2
                        img, com = take_img_calibration(cam2_index, cam_view = 1, threshold = cam2_threshold, avg_frames = 2, avg_com = 2)
                        # put in list
                        mot1_y_cam2_x[voltage_step] = com[0]
                        mot1_y_cam2_y[voltage_step] = com[1]
                        ui.gv_camera2.setImage(img, autoRange=False, autoLevels=False, autoHistogramRange=False)
                        # And save a list of the actual voltages
                        mot1_y_voltage[voltage_step] = voltage
                        # next step of calibration
                        calib_index += 1
                    else:
                        # If the voltage is not where it should be, update it.
                        motor_list[0].ch2_v = set_voltage
                        if reset_piezo > 0:  # Fuck it overide the tolerance, because now the code is improved to store the actual voltage
                            override = True
                        reset_piezo += 1
                elif motor_index == 2:
                    motor_list[0].ch2_v = starting_v[1]
                    # second motor, channel 1
                    voltage = motor_list[1].ch1_v
                    if (abs(voltage - set_voltage) < 0.2 or override):
                        time.sleep(0.2) #Give time between setting the piezo and measuring the COM
                        reset_piezo = 0
                        override = False
                        # update motor voltages
                        motor2_x = addToPlot(motor2_x, motor2_x_plot, voltage)
                        # get a frame from cam1 for x motor
                        img, com = take_img_calibration(cam1_index, cam_view = 0, threshold = cam1_threshold, avg_frames = 2, avg_com = 2)
                        # put in list, update image
                        mot2_x_cam1_x[voltage_step] = com[0]
                        mot2_x_cam1_y[voltage_step] = com[1]
                        ui.gv_camera1.setImage(img, autoRange=False, autoLevels=False, autoHistogramRange=False)
                        # get a frame from cam2 for x motor
                        img, com = take_img_calibration(cam2_index, cam_view = 1, threshold = cam2_threshold, avg_frames = 2, avg_com = 2)
                        # put in list
                        mot2_x_cam2_x[voltage_step] = com[0]
                        mot2_x_cam2_y[voltage_step] = com[1]
                        ui.gv_camera2.setImage(img, autoRange=False, autoLevels=False, autoHistogramRange=False)
                        # And save a list of the actual voltages
                        mot2_x_voltage[voltage_step] = voltage
                        # next step of calibration
                        calib_index += 1
                    else:
                        # If the voltage is not where it should be, update it.
                        motor_list[1].ch1_v = set_voltage
                        if reset_piezo > 0:  # Fuck it overide the tolerance, because now the code is improved to store the actual voltage
                            override = True
                        reset_piezo += 1
                elif motor_index == 3:
                    motor_list[1].ch1_v = starting_v[2]
                    # second motor, channel 2
                    voltage = motor_list[1].ch2_v
                    if (abs(voltage - set_voltage) < 0.2 or override):
                        time.sleep(0.2)  # Give time between setting the piezo and measuring the COM
                        reset_piezo = 0
                        override = False
                        # update motor voltages
                        motor2_y = addToPlot(motor2_y, motor2_y_plot, voltage)
                        # get a frame from cam1
                        img, com = take_img_calibration(cam1_index, cam_view = 0, threshold = cam1_threshold, avg_frames = 2, avg_com = 2)
                        # put in list
                        mot2_y_cam1_x[voltage_step] = com[0]
                        mot2_y_cam1_y[voltage_step] = com[1]
                        ui.gv_camera1.setImage(img, autoRange=False, autoLevels=False, autoHistogramRange=False)
                        # get a frame from cam2
                        img, com = take_img_calibration(cam2_index, cam_view = 1, threshold = cam2_threshold, avg_frames = 2, avg_com = 2)
                        # put in list
                        mot2_y_cam2_x[voltage_step] = com[0]
                        mot2_y_cam2_y[voltage_step] = com[1]
                        ui.gv_camera2.setImage(img, autoRange=False, autoLevels=False, autoHistogramRange=False)
                        # And save a list of the actual voltages
                        mot2_y_voltage[voltage_step] = voltage
                        # next step of calibration
                        calib_index += 1
                    else:
                        # If the voltage is not where it should be, update it.
                        motor_list[1].ch2_v = set_voltage
                        if reset_piezo > 0:  # Fuck it overide the tolerance, because now the code is improved to store the actual voltage
                            override = True
                        reset_piezo += 1
            else:
                # reset only last motor (the others were reset before moving next motor)
                motor_list[1].ch2_v = starting_v[3]
                # calculate slopes
                p_mot1_x_cam1_x = np.polyfit(mot1_x_voltage, mot1_x_cam1_x, deg=1)
                p_mot1_x_cam2_x = np.polyfit(mot1_x_voltage, mot1_x_cam2_x, deg=1)
                p_mot1_x_cam1_y = np.polyfit(mot1_x_voltage, mot1_x_cam1_y, deg=1)
                p_mot1_x_cam2_y = np.polyfit(mot1_x_voltage, mot1_x_cam2_y, deg=1)
                p_mot1_y_cam1_x = np.polyfit(mot1_y_voltage, mot1_y_cam1_x, deg=1)
                p_mot1_y_cam2_x = np.polyfit(mot1_y_voltage, mot1_y_cam2_x, deg=1)
                p_mot1_y_cam1_y = np.polyfit(mot1_y_voltage, mot1_y_cam1_y, deg=1)
                p_mot1_y_cam2_y = np.polyfit(mot1_y_voltage, mot1_y_cam2_y, deg=1)
                p_mot2_x_cam1_x = np.polyfit(mot2_x_voltage, mot2_x_cam1_x, deg=1)
                p_mot2_x_cam2_x = np.polyfit(mot2_x_voltage, mot2_x_cam2_x, deg=1)
                p_mot2_x_cam1_y = np.polyfit(mot2_x_voltage, mot2_x_cam1_y, deg=1)
                p_mot2_x_cam2_y = np.polyfit(mot2_x_voltage, mot2_x_cam2_y, deg=1)
                p_mot2_y_cam1_x = np.polyfit(mot2_y_voltage, mot2_y_cam1_x, deg=1)
                p_mot2_y_cam2_x = np.polyfit(mot2_y_voltage, mot2_y_cam2_x, deg=1)
                p_mot2_y_cam1_y = np.polyfit(mot2_y_voltage, mot2_y_cam1_y, deg=1)
                p_mot2_y_cam2_y = np.polyfit(mot2_y_voltage, mot2_y_cam2_y, deg=1)

                '''
                construct calibration matrix:
                Understand that this matrix is dV_i/dx_j where ij indexes like a normal matrix, i.e. row column. 
                Therefore, dV = calib_mat * dx where dx is a column vector, [d_cam1_x, d_cam1_y, d_cam2_x, d_cam2_y].Transpose,
                where, for example, d_cam1_x is the difference in the desired position of cam1_x and the calculated COM x_coordinate of cam 1.
                and dV is a column vector, [d_mot1_x, d_mot1_y, d_mot2_x, d_mot2_y,].Transpose, i.e. the change in voltage
                 on each motor to bring the COM coordinates to desired position.
                Therefore, this matrix can be used to update the motor voltages as New_V = Old_V + calib_mat*dx 
                '''
                calib_mat = np.array([[p_mot1_x_cam1_x[0], p_mot1_y_cam1_x[0], p_mot2_x_cam1_x[0], p_mot2_y_cam1_x[0]],
                                        [p_mot1_x_cam1_y[0], p_mot1_y_cam1_y[0], p_mot2_x_cam1_y[0], p_mot2_y_cam1_y[0]],
                                        [p_mot1_x_cam2_x[0], p_mot1_y_cam2_x[0], p_mot2_x_cam2_x[0], p_mot2_y_cam2_x[0]],
                                        [p_mot1_x_cam2_y[0], p_mot1_y_cam2_y[0], p_mot2_x_cam2_y[0], p_mot2_y_cam2_y[0]]])
                calib_mat = np.linalg.inv(calib_mat)
                try:
                    old_calib_mat = np.loadtxt('Most_Recent_Calibration.txt', dtype=int)
                    Change = np.sqrt(np.sum(np.square(calib_mat)-np.square(old_calib_mat)))
                    RelativeChange = Change/np.sqrt(np.sum(np.square(old_calib_mat)))
                    print(RelativeChange)
                except OSError:
                    pass
                print('Calibration done!')
                print(calib_mat)
                np.savetxt('Most_Recent_Calibration.txt', calib_mat, fmt='%d')
                state = STATE_MEASURE

    def updateMeasure():
        """
        GUI update function
        """
        # TODO: talk to piezo controller
        global saturated_cam1, under_saturated_cam1, saturated_cam2, under_saturated_cam2
        global cam1_reset, cam2_reset
        global cam1_x, cam1_y, cam2_x, cam2_y
        global cam1_x_time, cam1_y_time, cam2_x_time, cam2_y_time
        ############################
        # Camera 1 update function #
        ############################
        if cam1_index >= 0:
            if cam1_reset:
                _, _, _, under_saturated_cam1, saturated_cam1 = take_img(cam1_index, cam_view=0, threshold=cam1_threshold, resetView=True)
                cam1_reset = False
            else:
                _, _, _, under_saturated_cam1, saturated_cam1 = take_img(cam1_index, cam_view=0, threshold=cam1_threshold, resetView=False)
        else:
            cam1_x_line.setVisible(False)
            cam1_y_line.setVisible(False)
        ############################
        # Camera 2 update function #
        ############################
        if cam2_index >= 0:
            if cam2_reset:
                _, _, _, under_saturated_cam2, saturated_cam2 = take_img(cam2_index, cam_view=1, threshold=cam2_threshold, resetView=True)
                cam2_reset = False
            else:
                _, _, _, under_saturated_cam2, saturated_cam2 = take_img(cam2_index, cam_view=1, threshold=cam2_threshold, resetView=False)
        else:
            cam2_x_line.setVisible(False)
            cam2_y_line.setVisible(False)

    def updateLocked():
        global calib_mat
        global LockTimeStart, TimeLastUnlock
        global num_out_of_voltage_range #Track the number of times the voltage update goes out of range during lock
        global state
        global set_cam1_x, set_cam1_y, set_cam2_x, set_cam2_y
        global saturated_cam1, under_saturated_cam1, saturated_cam2, under_saturated_cam2
        global cam1_reset, cam2_reset
        global cam1_x_time, cam1_y_time, cam2_x_time, cam2_y_time
        if np.trace(np.matmul(calib_mat,calib_mat))==4:
            try:
                calib_mat = np.loadtxt('Most_Recent_Calibration.txt', dtype=int)
            except OSError:
                state = STATE_MEASURE
                raise FileNotFoundError("Hmm there seems to be no saved calibration, rerun calibration.")
        if cam1_index >= 0 and cam2_index >= 0 and cam1_index != cam2_index:
            if cam1_reset:
                _, com1_x, com1_y, under_saturated_cam1, saturated_cam1 = take_img(cam1_index, cam_view=0,
                                                                                   threshold=cam1_threshold,
                                                                                   resetView=True)
                cam1_reset = False
            else:
                _, com1_x, com1_y, under_saturated_cam1, saturated_cam1 = take_img(cam1_index, cam_view=0,
                                                                                   threshold=cam1_threshold,
                                                                                   resetView=False)
            if cam2_reset:
                _, com2_x, com2_y, under_saturated_cam2, saturated_cam2 = take_img(cam2_index, cam_view=1,
                                                                                   threshold=cam2_threshold,
                                                                                   resetView=True)
                cam2_reset = False
            else:
                _, com2_x, com2_y, under_saturated_cam2, saturated_cam2 = take_img(cam2_index, cam_view=1,
                                                                                   threshold=cam2_threshold,
                                                                                   resetView=False)
            # Calculate dX
            # The convention here is how much has the position on the camera changed from the set point.
            cam1_dx = com1_x - set_cam1_x
            cam1_dy = com1_y - set_cam1_y
            cam2_dx = com2_x - set_cam2_x
            cam2_dy = com2_y - set_cam2_y
            dX = np.array([cam1_dx, cam1_dy, cam2_dx, cam2_dy])
            # Because of our convention for dX, the meaning of dV is how much would the voltages have changed to result
            # in the change observed in dX
            dV = np.matmul(calib_mat, dX)
            dV = np.floor(10*dV)/10  # Round down on tenths decimal place, motors do not like more than 1 decimal place.
            # voltage to be set on the motors
            # Of course, the dX is not from a voltage change but from some change in the laser; so we remove the
            # "voltage change" that would have caused dX. That is, the positions moved as though Voltages changed by dV;
            # so we subtract that dV restoring us to the old position.
            update_voltage = np.array([motor_list[0].ch1_v, motor_list[0].ch2_v, motor_list[1].ch1_v,
                                       motor_list[1].ch2_v])-dV
            # update voltages
            if np.any(update_voltage>150) or np.any(update_voltage<0):
                # This section of code basically resets the voltages and skips the update this time, but it allows
                # the code to try to relock after resetting the voltages. However, this code tracks the number of times
                # that the voltages went out of bounds in less than 1 minute since the last reset (i.e. if it resets and
                # then locks for more than 1 minute, the counter is reset to 0). If the piezos go out of bounds more than
                # 10 times in a row in less than a minute each time, then the code unlocks and returns to measuring state.
                print("Warning: The update voltages went out of range, resetting piezos and attempting to relock")
                # Reset the voltages to 75.0 the OG settings, and skip this update. Try again.
                motor_list[0].ch1_v = 75.0
                motor_list[0].ch2_v = 75.0
                motor_list[1].ch1_v = 75.0
                motor_list[1].ch2_v = 75.0
                first_unlock = False #First time since initial lock that piezos went out of bounds?
                # Track time since last unlock and the number of times unlocked in less than 1 minute since previous
                # lock.
                if TimeLastUnlock == 0:
                    first_unlock = True
                    TimeLastUnlock = time.monotonic()
                if time.monotonic()-TimeLastUnlock < 60.0 or first_unlock:
                    num_out_of_voltage_range += 1
                else:
                    num_out_of_voltage_range = 1
                if num_out_of_voltage_range > 10:
                    num_out_of_voltage_range = 0
                    TimeLastUnlock = 0
                    state = STATE_MEASURE
                    successful_lock_time = time.monotonic() - LockTimeStart
                    print("Successfully locked pointing for", successful_lock_time)
                    raise NotImplementedError('The piezo voltages have gone outside of the allowed range! Stop Lock')
            else:
                motor_list[0].ch1_v = update_voltage[0]
                motor_list[0].ch2_v = update_voltage[1]
                motor_list[1].ch1_v = update_voltage[2]
                motor_list[1].ch2_v = update_voltage[3]
        else:
            if cam1_index < 0:
                cam1_x_line.setVisible(False)
                cam1_y_line.setVisible(False)
            if cam2_index < 0:
                cam2_x_line.setVisible(False)
                cam2_y_line.setVisible(False)

    '''
    Archived...
    def updateLocked():
        global cailb_x, calib_y 
        global set_cam1_x, set_cam1_y, set_cam2_x, set_cam2_y
        global saturated_cam1, under_saturated_cam1, saturated_cam2, under_saturated_cam2
        global cam1_reset, cam2_reset
        global cam1_x_time, cam1_y_time, cam2_x_time, cam2_y_time
        if cam1_index >= 0 and cam2_index >= 0 and cam1_index != cam2_index:
            if cam1_reset:
                _, com1_x, com1_y, under_saturated_cam1, saturated_cam1 = take_img(cam1_index, cam_view=0, threshold=cam1_threshold, resetView=True)
                cam1_reset = False
            else:
                _, com1_x, com1_y, under_saturated_cam1, saturated_cam1 = take_img(cam1_index, cam_view=0, threshold=cam1_threshold, resetView=False)
            if cam2_reset:
                _, com2_x, com2_y, under_saturated_cam2, saturated_cam2 = take_img(cam2_index, cam_view=1, threshold=cam2_threshold, resetView=True)
                cam2_reset = False
            else:
                _, com2_x, com2_y, under_saturated_cam2, saturated_cam2 = take_img(cam2_index, cam_view=1, threshold=cam2_threshold, resetView=False)
            cam1_dx = set_cam1_x - com1_x
            cam1_dy = set_cam1_y - com1_y
            cam2_dx = set_cam2_x - com2_x
            cam2_dy = set_cam2_x - com2_y
            #These are changes in voltage, not the actual voltage to be applied?
            v_x = np.dot(calib_x, np.array([cam1_dx, cam2_dx]))
            v_y = np.dot(calib_y, np.array([cam1_dy, cam2_dy]))

            #update voltages
            motor_list[0].ch1_v = v_x[0]+motor_list[0]._ch1_v
            motor_list[1].ch1_v = v_x[1]+motor_list[1]._ch1_v
            motor_list[0].ch2_v = v_y[0]+motor_list[0]._ch2_v
            motor_list[1].ch2_v = v_y[0]+motor_list[1]._ch2_v
        else:
            if cam1_index < 0:
                cam1_x_line.setVisible(False)
                cam1_y_line.setVisible(False)
            if cam2_index < 0:
                cam2_x_line.setVisible(False)
                cam2_y_line.setVisible(False)
    '''

    def update_cam1_settings():
        global cam1_index, cam1_threshold, cam1_reset
        cam1_index = int(ui.cb_cam1.currentIndex())
        cam1_exp_time = float(ui.le_cam1_exp_time.text())
        cam1_gain = float(ui.le_cam1_gain.text())
        cam1_threshold = float(ui.le_cam1_threshold.text())
        cam1_decimate = ui.cb_cam1_decimate.isChecked()
        cam_list[cam1_index].set_gain(cam1_gain)
        cam_list[cam1_index].set_exposure_time(cam1_exp_time)
        cam_list[cam1_index].set_decimation(cam1_decimate)
        ui.le_cam1_exp_time.setText('%.2f' % (cam_list[cam1_index].exposure_time))
        ui.le_cam1_gain.setText('%.2f' % (cam_list[cam1_index].gain/8))
        cam1_reset = True
        resetHist(ui.gv_camera1)
    
    def update_cam2_settings():
        global cam2_index, cam2_threshold, cam2_reset
        cam2_index = int(ui.cb_cam2.currentIndex())
        cam2_exp_time = float(ui.le_cam2_exp_time.text())
        cam2_gain = float(ui.le_cam2_gain.text())
        cam2_threshold = float(ui.le_cam2_threshold.text())
        cam2_decimate = ui.cb_cam2_decimate.isChecked()
        cam_list[cam2_index].set_gain(cam2_gain)
        cam_list[cam2_index].set_exposure_time(cam2_exp_time)
        cam_list[cam2_index].set_decimation(cam2_decimate)
        ui.le_cam2_exp_time.setText('%.2f' % (cam_list[cam2_index].exposure_time))
        ui.le_cam2_gain.setText('%.2f' % (cam_list[cam2_index].gain/8))
        cam2_reset = True
        resetHist(ui.gv_camera2)
    
    def update_motors():
        global motor1_index, motor2_index
        global motor_list, resourceManager
        motor1_index = ui.cb_motors_1.currentIndex()
        motor2_index = ui.cb_motors_2.currentIndex()
        if motor1_index != motor2_index:
            motor_list = []
            #Garrison Updated to add "0" inside ui.cb_motors_1.currentData(0)
            motor_list.append(MDT693A_Motor(resourceManager, com_port=ui.cb_motors_1.currentData(0), ch1='X', ch2='Y'))
            motor_list.append(MDT693A_Motor(resourceManager, com_port=ui.cb_motors_2.currentData(0), ch1='X', ch2='Y'))
            #motor_list.append(MDT693A_Motor(resourceManager, com_port=ui.cb_motors_1.currentData(), ch1='X', ch2='Y'))
            #motor_list.append(MDT693A_Motor(resourceManager, com_port=ui.cb_motors_2.currentData(), ch1='X', ch2='Y'))
        #motor_list.append(FakeMotor('X', 'Y'))
        #motor_list.append(FakeMotor('X', 'Y'))
        #print('Connected two fake motors!')
    
    def begin_calibration():
        global state, starting_v, motor_list, calib_index
        calib_index = 0
        if len(motor_list) == 0:
            update_motors()
        starting_v[0] = motor_list[0].ch1_v
        starting_v[1] = motor_list[0].ch2_v
        starting_v[2] = motor_list[1].ch1_v
        starting_v[3] = motor_list[1].ch1_v
        state = STATE_CALIBRATE
    
    def clear_pointing_plots():
        global cam1_x, cam1_y, cam2_x, cam2_y
        cam1_x = np.array([])
        cam1_y = np.array([])
        cam2_x = np.array([])
        cam2_y = np.array([])
    
    def lock_pointing():
        if (ui.btn_lock.isChecked()):
            global set_cam1_x, set_cam1_y, set_cam2_x, set_cam2_y
            global cam1_x, cam1_y, cam2_x, cam2_y
            global state
            if cam1_index >= 0 and cam2_index >= 0:
                set_cam1_x = cam1_x[-1]
                set_cam1_y = cam1_y[-1]
                set_cam2_x = cam2_x[-1]
                set_cam2_y = cam2_y[-1]
                print('Set cam 1 x', set_cam1_x)
                print('Set cam 1 y', set_cam1_y)
                print('Set cam 2 x', set_cam2_x)
                print('Set cam 2 y', set_cam2_y)
                state = STATE_LOCKED
            else:
                ui.btn_lock.toggle()
        else:
            state = STATE_MEASURE


    ui.btn_cam1_update.clicked.connect(update_cam1_settings)
    ui.btn_cam2_update.clicked.connect(update_cam2_settings)
    ui.btn_motor_connect.clicked.connect(update_motors)
    ui.act_calibrate.triggered.connect(begin_calibration)
    ui.btn_clear.clicked.connect(clear_pointing_plots)
    ui.btn_lock.clicked.connect(lock_pointing)

    timer = QtCore.QTimer()
    timer.timeout.connect(update)
    timer.start(UPDATE_TIME)
    MainWindow.show()

    sys.exit(app.exec_())
