import numpy as np
from PyQt5 import uic
from PyQt5.QtWidgets import *
from PyQt5.QtWidgets import QLineEdit
import sys
from vispy import scene
import vispy.scene
from custom_util import prompt_saving, prompt_deleting, floodfill, crop_reserve, crop_remove, FloodfillError, Scene
from models import Segment
import os
import open3d as o3d


class AtlasAnnotationTool(QWidget):
    def __init__(self, app):
        super(AtlasAnnotationTool, self).__init__()
        base_form, window = uic.loadUiType("main.ui")
        self.window = window()
        self.base_form = base_form()
        self.base_form.setupUi(self.window)

        # bookkeeping variable
        self.data_fname = "segments.json"
        self.point_size = 3.5
        self.message = "> Program Started, UI Loaded"
        self.selected_points_id = []
        self.largest_seg_id = -1
        self.segmentations = [] # list of segmentations of type Segmentation

        self.current_data_file_name = None
        self.current_result_point_indices = []

        # scene variables -- common
        self.upperScene = Scene()
        self.lowerScene = Scene()
        self.message_center = None
        self.segmentation_list = None
        self.btn_common_save = None
        self.btn_common_load = None
        self.btn_common_delete = None

        # scene variable -- floodfill specific buttons
        self.btn_floodfill_done = None
        self.btn_floodfill_cancel = None

        # setup
        self.setUpDisplay()
        self.wireWidgets()
        self.setOnClickListener()
        self.populateSegmentList()

        # keep track of selected points
        self.selected = {}

        # Demo
        # self.addSegmentationItems(["Placeholder 1", "Placeholder 2"])
        # pcd = o3d.io.read_point_cloud("./data/scene.ply")
        # self.upperScene.render(pcd)
        self.window.show()
        app.exec_()

    ####### SET UP FUNCTIONS #######

    def setOnClickListener(self):
        self.btn_floodfill_done.clicked.connect(self.btn_floodfill_done_clicked)
        self.btn_floodfill_cancel.clicked.connect(self.btn_floodfill_cancel_clicked)
        self.upperScene.canvas.events.mouse_release.connect(self.topCanvasClicked)
        self.btn_common_load.clicked.connect(self.btn_common_load_clicked)
        self.btn_common_save.clicked.connect(self.btn_save_clicked)
        self.btn_common_delete.clicked.connect(self.btn_delete_clicked)
        self.segmentation_list.itemDoubleClicked.connect(self.segmentation_list_item_double_clicked)
        # crop button
        self.btn_crop.clicked.connect(self.btn_crop_clicked)

    def wireWidgets(self):
        # scene wiring
        self.base_form.data_display_window.addWidget(self.upperScene.canvas.native)
        self.base_form.data_display_window.addWidget(self.lowerScene.canvas.native)

        # message box wiring
        self.message_center = self.base_form.message_center_layout.itemAt(0).widget()

        # segmentation list wiring
        self.segmentation_list = self.base_form.segmentation_layout.itemAt(0).widget()
        # scene button wiring
        self.btn_common_save = self.base_form.common_buttons_layout.itemAt(0).widget()
        self.btn_common_load = self.base_form.common_buttons_layout.itemAt(1).widget()
        self.btn_common_delete = self.base_form.common_buttons_layout.itemAt(2).widget()

        # Floodfill wiring
        tab_floodfill = self.base_form.system_mode_layout.itemAt(0).widget()
        self.btn_floodfill_done = tab_floodfill.widget(0).children()[1]
        self.btn_floodfill_cancel = tab_floodfill.widget(0).children()[2]

        # Coordinate Crop wiring
        tab_crop = self.base_form.system_mode_layout.itemAt(0).widget()
        self.btn_crop = tab_crop.widget(1).children()[0].children()[5]
        self.x_coord = tab_crop.widget(1).children()[0].children()[2]
        self.y_coord = tab_crop.widget(1).children()[0].children()[3]
        self.z_coord = tab_crop.widget(1).children()[0].children()[4]

        # QT Designer reference: https://doc.qt.io/qtcreator/creator-using-qt-designer.html

    def setUpDisplay(self):
        self.upperScene.canvas = vispy.scene.SceneCanvas(keys='interactive', show=True)
        self.lowerScene.canvas = vispy.scene.SceneCanvas(keys='interactive', show=True)

    ####### ON CLICK FUNCTIONS #######

    def segmentation_list_item_double_clicked(self):
        '''
        When an item is double clicked, read that file and render it onto the upper scene
        '''
        current_item_text = self.segmentation_list.currentItem().text()
        try:
            current_item_index = int(current_item_text.split(" | ")[0])
            current_segmentation = self.segmentations[current_item_index]
            index_to_highlight = current_segmentation.indices
            fname = str(current_segmentation.data_file_name)

            pcd = o3d.io.read_point_cloud(fname)
            class DataPCDIsEmptyException(Exception):
                pass
            if pcd.is_empty():
                raise DataPCDIsEmptyException("ERR: Data file at {} is cannot be found or is empty".format(fname))

            color = np.asarray(pcd.colors)
            for i in index_to_highlight:
                color[i] = (0, 1, 0)
            pcd.colors = o3d.utility.Vector3dVector(color)

            self.upperScene.render(pcd)
        except ValueError as e:
            self.writeMessage("ERR: Index is not an int --> {}".format(current_item_text.split(" | ")[0]))


    def btn_common_load_clicked(self):
        '''
        When load is clicked, load the file and render it onto the upper scene
        '''
        filename = self.openFileNamesDialog()
        # do filetype checking here
        if filename:
            self.current_data_file_name = filename
            self.writeMessage("Opening file <{}>".format(filename))
            self.upperScene.render(o3d.io.read_point_cloud(filename))

    def btn_floodfill_done_clicked(self):
        '''
        When the floodfill button is clicked
        1. get the selected points
        2. get the surface that needs to be cropped
        3. render the result in the lower scene
        '''
        # revert to original colors
        self.clearSelected()
        try:
            surface_to_crop = floodfill(self.selected_points_id, self.upperScene.pcd)
            self.current_result_point_indices = surface_to_crop
            new_pcd = crop_reserve(self.upperScene.pcd, surface_to_crop)
            self.lowerScene.render(new_pcd)

        except Exception as e:
            self.writeMessage(str(e))
        self.writeMessage("Selected Points Cleared")
        self.selected_points_id = []


    def btn_floodfill_cancel_clicked(self):
        '''
        When cancel is clicked
        1. clear all selected points
        2. clear the lower scene
        '''
        self.writeMessage("Selected Segmenation Cancelled")
        self.selected_points_id = []
        self.current_result_point_indices = []
        self.lowerScene.clear()
        self.clearSelected()

    def btn_delete_clicked(self):
        '''
        When delete is clicked
        1. Prompt the user for the name of the save/object
        2. Delete the object from the segmentation_list
        3. Delete the object from segments.json
        4. Reorder the remaining objects
        5. Delete segments.json if there are no remaining saves
        '''
        # prompt the user for a save to delete and pass in the available segment_name's
        name = prompt_deleting([s.segment_name for s in self.segmentations])
        import json
        with open(self.data_fname, mode='r') as f:
            segmentations = json.load(f)
        # data to be saved in segments.json
        data = []

        # initialize removed_id to be an out-of-bounds value (will be updated in the loop)
        removed_id = len(segmentations)

        for segment in segmentations:
            segment_dict = json.loads(segment)
            seg = Segment(**segment_dict)
            if seg.segment_name != name:

                # reorder remaining Segments if deletion has already been performed
                if seg.id > removed_id:
                    seg.id -= 1

                    # https://doc.qt.io/qtforpython/PySide2/QtWidgets/QListWidgetItem.html
                    self.segmentation_list.item(seg.id).setText("{} | {} | {}".format(seg.id, seg.segment_name, seg.type_class))

                    # save the new id in the backend
                    self.segmentations[seg.id].id -= 1
                entry = seg.json()
                data.append(entry)
            else:
                # remove the selected Segment from backend
                self.segmentations.pop(seg.id)

                # remove the selected Segment from frontend (https://doc.qt.io/archives/qt-4.8/qlistwidget.html#takeItem)
                self.segmentation_list.takeItem(seg.id)

                # save the removed_id to reorder subsequent Segments
                removed_id = seg.id

        # delete segments.json if no Segments remain
        if not data:
            os.remove(self.data_fname)
        # otherwise, save the remaining Segments
        else:
            with open(self.data_fname, mode='w') as f:
                f.write(json.dumps(data, indent=2))

    def btn_save_clicked(self):
        '''
        When save is clicked
        1. Prompt the user for the name and type of the object
        2. save the object
        '''
        data = prompt_saving()
        if len(self.current_result_point_indices) == 0:
            self.writeMessage("There are no points to save")
        else:
            import json
            a = []
            if not os.path.isfile(self.data_fname):
                self.largest_seg_id = self.largest_seg_id + 1
                segment = Segment(id=self.largest_seg_id,
                                  data_file_name=self.current_data_file_name,
                                  segment_name=data["seg_name"],
                                  indices=self.current_result_point_indices,
                                  type_class=(data["type_class"], 1)
                                  )
                self.addSegmentationItem(segment)
                entry = segment.json()
                a.append(entry)
                with open(self.data_fname, mode='w') as f:
                    f.write(json.dumps(a, indent=2))
            else:
                with open(self.data_fname) as feedsjson:
                    feeds = json.load(feedsjson)
                self.largest_seg_id = len(feeds)
                segment = Segment(id=self.largest_seg_id,
                                  data_file_name=self.current_data_file_name,
                                  segment_name=data["seg_name"],
                                  indices=self.current_result_point_indices,
                                  type_class=(data["type_class"], 1)
                                  )
                self.addSegmentationItem(segment)
                entry = segment.json()
                feeds.append(entry)
                with open(self.data_fname, mode='w') as f:
                    f.write(json.dumps(feeds, indent=2))
            self.lowerScene.clear()

    def topCanvasClicked(self, event):
        '''
        When the top canvas is clicked
        1. rotate the scene if necessary
        2. record the point clicked if necessary
        3. show the points clicked
        :param event: event that the top canvas is clicked.
        :return:
        '''
        pcd = self.upperScene.pcd
        points = np.asarray(pcd.points)
        colors = np.asarray(pcd.colors)
        # axis = scene.visuals.XYZAxis(parent=self.upper.scene)

        # prepare list of unique colors needed for picking
        ids = np.arange(1, len(points) + 1, dtype=np.uint32).view(np.uint8)
        ids = ids.reshape(-1, 4)
        ids = np.divide(ids, 255, dtype=np.float32)
        # connect events
        distance = self.distance_traveled(event.trail())
        if event.button == 1 and distance <= 2:
            pos = self.upperScene.canvas.transforms.canvas_transform.map(event.pos)
            try:
                self.upperScene.marker.update_gl_state(blend=False)
                self.upperScene.marker.antialias = 0
                self.upperScene.marker.set_data(points, edge_color=ids, face_color=ids, size=self.point_size)
                img = self.upperScene.canvas.render((pos[0] - 2,
                                                     pos[1] - 2,
                                                     2 * 10 + 1,
                                                     2 * 10 + 1),
                                                    bgcolor=vispy.color.ColorArray('red'))
                self.upperScene.canvas.update()
            finally:
                self.upperScene.marker.update_gl_state(blend=True)
                self.upperScene.marker.antialias = 1
                self.upperScene.marker.set_data(points, edge_color=colors, face_color=colors, size=self.point_size)
            # We pick the pixel directly under the click, unless it is
            # zero, in which case we look for the most common nonzero
            # pixel value in a square region centered on the click.
            idxs = img.ravel().view(np.uint32)
            idx = idxs[len(idxs) // 2]

            if idx == 0:
                idxs, counts = np.unique(idxs, return_counts=True)
                idxs = idxs[np.argsort(counts)]
                idx = idxs[-1] or (len(idxs) > 1 and idxs[-2])
            # call the callback function
            if idx > 0:
                try:
                    points[idx]
                    # restrict repeated points
                    if idx not in self.selected:
                        self.selected_points_id.append(idx)
                        # p1.set_data(points, edge_color=colors, face_color=colors, size=2)
                        
                        # save the original color of the point in a copy (https://numpy.org/doc/stable/reference/generated/numpy.ndarray.copy.html)
                        self.selected[idx] = np.ndarray.copy(colors[idx])

                        # set the selected point's color to red
                        colors[idx] = (1, 0, 0)

                        # re-render with updated colors
                        self.upperScene.marker.set_data(points, edge_color=colors, face_color=colors, size=self.point_size)
                        self.upperScene.canvas.update()
                        self.writeMessage("Selected Points: {}".format(self.selected_points_id))
                    else:
                        self.writeMessage("Please select a distinct point.")
                except IndexError:
                    self.writeMessage("The point {} is not in the point cloud".format(idx))

    def btn_crop_clicked(self):
        '''
        When crop is clicked
        1. Get the selected coordinates
        2. Check for malformed inputs
        3. Remove the cropped area
        4. Render the result in the lower scene
        '''
        # accessing QLineEdit inputs: https://stackoverflow.com/questions/3016974/how-to-get-text-in-qlineedit-when-qpushbutton-is-pressed-in-a-string
        coords = {"X": self.x_coord.text(), "Y": self.y_coord.text(), "Z": self.z_coord.text()}
        if not all(coords.values()):
            missing = ""
            for k in coords:
                if not coords[k]:
                    missing += k + ", "
            missing = missing[:len(missing) - 2]
            self.writeMessage("Missing coordinate(s): " + missing)
        else:
            values = []
            for k in coords:
                try:
                    values.append(int(coords[k]))
                except ValueError:
                    self.writeMessage("Coordinates must be integers.")
                    return
            try:
                pcd = self.upperScene.pcd
                points = np.asarray(pcd.points)
                new_pcd = crop_remove(pcd, values)
                self.lowerScene.render(new_pcd)
                self.current_result_point_indices = values
            except Exception as e:
                self.writeMessage(str(e))

    ####### UTILITIES FUNCTIONS #######

    def clearSelected(self):
        """
        Recolor all selected points back to their original colors.
        """
        pcd = self.upperScene.pcd
        points = np.asarray(pcd.points)
        colors = np.asarray(pcd.colors)
        for pt in self.selected:
            colors[pt] = self.selected[pt]
        self.selected = {}
        self.upperScene.marker.set_data(points, edge_color=colors, face_color=colors, size=self.point_size)
        self.upperScene.canvas.update()

    def openFileNamesDialog(self):
        options = QFileDialog.Options()
        options |= QFileDialog.DontUseNativeDialog
        files, _ = QFileDialog.getOpenFileNames(self, "QFileDialog.getOpenFileNames()", "",
                                                "All Files (*);;Python Files (*.py)", options=options)
        if files:
            return files[0]
        return None

    @staticmethod
    def distance_traveled(positions):
        """
        Return the total amount of pixels traveled in a sequence of pixel
        `positions`, using Manhattan distances for simplicity.
        """
        try:
            return np.sum(np.abs(np.diff(positions, axis=0)))
        except Exception as e:
            return 0

    def addSegmentationItem(self, segment):
        self.segmentations.append(segment)
        self.segmentation_list.addItem("{} | {} | {}".format(segment.id, segment.segment_name, segment.type_class))

    def writeMessage(self, message):
        '''
        Iteratively populate message
        :param message: new message given
        '''
        self.message = "{} \n> {}".format(self.message, message)  # format the text so that it is one per line
        self.message_center.setPlainText(self.message)  # no url displaying
        self.message_center.verticalScrollBar().setValue(
            self.message_center.verticalScrollBar().maximum())  # scroll bar to the bottom by default

    def populateSegmentList(self):
        '''
        On start, populate a list of segmentations that user previously did
        '''
        try:
            import json
            with open(self.data_fname, 'r') as f:
                segmentations = json.load(f)
            for segment in segmentations:
                segment_dict = json.loads(segment)
                seg = Segment(**segment_dict)
                self.addSegmentationItem(seg)
        except FileNotFoundError as e:
            self.writeMessage("No segmentations detected")

if __name__ == '__main__':
    app = QApplication(sys.argv)
    annotation_tool = AtlasAnnotationTool(app)
