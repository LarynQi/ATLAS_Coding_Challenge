import numpy as np
import open3d as o3d
from vispy.scene import visuals
from PyQt5.QtWidgets import *
# Print iterations progress
def printProgressBar(iteration, total, prefix='', suffix='', decimals=1, length=100, fill='█'):
    """
    Call in a loop to create terminal progress bar
    @params:
        iteration   - Required  : current iteration (Int)
        total       - Required  : total iterations (Int)
        prefix      - Optional  : prefix string (Str)
        suffix      - Optional  : suffix string (Str)
        decimals    - Optional  : positive number of decimals in percent complete (Int)
        length      - Optional  : character length of bar (Int)
        fill        - Optional  : bar fill character (Str)
    """
    percent = ("{0:." + str(decimals) + "f}").format(100 * (iteration / float(total)))
    filledLength = int(length * iteration // total)
    bar = fill * filledLength + '-' * (length - filledLength)
    print('\r%s |%s| %s%% %s' % (prefix, bar, percent, suffix), end='\r')
    # Print New Line on Complete
    if iteration == total:
        print()



def angle_between(v1, v2):
    """ Returns the angle in radians between vectors 'v1' and 'v2', given that v1 and v2 are unit vectors:
    """
    return np.arccos(np.clip(np.dot(v1, v2), -1, 1))


def findNearestNeighbor(pcd, pcd_tree, current_point_id, batch_size):
    return pcd_tree.search_knn_vector_3d(pcd.points[current_point_id],
                                         batch_size)


def crop_remove(pcd, points_to_delete):
    points = np.asarray(pcd.points)
    colors = np.asarray(pcd.colors)

    # https://numpy.org/doc/stable/reference/generated/numpy.delete.html
    temp = points_to_delete[:]
    temp.remove(max(points_to_delete))
    delete1 = np.s_[min(points_to_delete):max(temp)]
    delete2 = np.s_[max(temp):max(points_to_delete)]
    delete3 = np.s_[min(points_to_delete):max(points_to_delete)]

    # updated_points = np.delete(points, points_to_delete, axis=0)
    updated_points = np.delete(points, delete1, axis=0)
    updated_points = np.delete(updated_points, delete2, axis=0)
    updated_points = np.delete(updated_points, delete3, axis=0)

    # updated_color = np.delete(colors, points_to_delete, axis=0)
    updated_color = np.delete(colors, delete1, axis=0)
    updated_color = np.delete(updated_color, delete2, axis=0)
    updated_color = np.delete(updated_color, delete3, axis=0)

    pcd_updated = o3d.geometry.PointCloud()
    pcd_updated.points = o3d.utility.Vector3dVector(updated_points)
    pcd_updated.colors = o3d.utility.Vector3dVector(updated_color)
    return pcd_updated


def crop_reserve(pcd, points_to_reserve):
    points = np.asarray(pcd.points)
    colors = np.asarray(pcd.colors)

    updated_points = np.take(points, points_to_reserve, axis=0)
    updated_color = np.take(colors, points_to_reserve, axis=0)

    pcd_updated = o3d.geometry.PointCloud()
    pcd_updated.points = o3d.utility.Vector3dVector(updated_points)
    pcd_updated.colors = o3d.utility.Vector3dVector(updated_color)
    return pcd_updated


def generate_line_points(p1, p2, num_points=10000):
    '''
    @param -- two points that are on the same plane
        p1 -- starting point, format in numpy array or list of x,y,z]
        p2 -- ending point, format in numpy array or list of [x,y,z]
    @return numpy of points of shape (num_points,3)
    '''
    x = np.linspace(p1[0], p2[0], num_points)
    y = np.linspace(p1[1], p2[1], num_points)
    z = np.linspace(p1[2], p2[2], num_points)
    return np.array(list(zip(x, y, z)))


class BoundingLine():
    '''
    Sample usage:
        p1 = [0,0,0]
        p2 = [1,1,1]
        p = [2,3,2]
        axis = (0,1)
        bounding_line = BoudingLine(p1,p2,p,axis)
        print(bounding_line.checkSide([2,2,2]))
    '''

    def __init__(self, line_start, line_end):
        self.line_start = line_start
        self.line_end = line_end

    def __str__(self):
        return " line_start: {} |  line_end: {} | seed: {} ".format(self.line_start, self.line_end, )


def check_neighbor_condition(normals, coordinates, seed_id, current_neighbor, bounding_line, angle_error_tolerance):
    if check_angle_condition(normals, seed_id, current_neighbor, angle_error_tolerance) \
            and check_distance(bounding_line, coordinates, current_neighbor):
        return True
    return False


def check_angle_condition(normals, seed_id, current_neighbor, angle_error_tolerance):
    return angle_between(normals[seed_id], normals[current_neighbor]) < angle_error_tolerance


def check_distance(bounding_line, coordinates, current_neighbor, threshold=0.1):
    '''
    algorithm from wolfram alpha: http://mathworld.wolfram.com/Point-LineDistance3-Dimensional.html
    '''
    x0 = coordinates[current_neighbor]
    x1 = bounding_line.line_start
    x2 = bounding_line.line_end
    d = np.linalg.norm(np.cross(x0 - x1, x0 - x2)) / np.linalg.norm(x2 - x1)
    # result = all(x > 0.001 for x in d)
    # print(d)
    return d > threshold


def check_bounding_condition(bounding_line, coordinates, current_neighbor):
    return bounding_line.check(coordinates[current_neighbor])


class FloodfillError(Exception):
    pass


def floodfill(picked_points_id, pcd, batch_size=10, angle_error_tolerance=0.4, boundary_thickness=0.1):
    '''
    Floodfill until a given line is hit
    :param picked_points_id: list of points that user picked
    :param pcd: the Open3D pcd file
    :param batch_size: at one time, how many points do we consider
    :param angle_error_tolerance: the err tolerance for how different the normal vector between the two points that we consider them to be on the same plane
    :param boundary_thickness: how close to the boundary do we consider a point to hit the boundary
    :return: resulting surface are within the floodfilling reach of the current boudning line and seed point
    '''
    if len(picked_points_id) != 3:
        raise FloodfillError(
            "ERROR: {} points is chosen, only 3 point floodfill is implemented".format(len(picked_points_id)))
    # set up
    pcd_tree = o3d.geometry.KDTreeFlann(pcd)
    pcd.estimate_normals()
    normals = np.asarray(pcd.normals)
    coordinates = np.asarray(pcd.points)

    bounding_line = BoundingLine(coordinates[picked_points_id[0]], coordinates[picked_points_id[1]])
    seed_id = picked_points_id[2]
    points_to_check = {seed_id}

    surface = set()

    counter = 0
    while len(points_to_check) != 0:
        current_point_id = points_to_check.pop()
        # find neighbors
        [k, idx, _] = findNearestNeighbor(pcd, pcd_tree, current_point_id,
                                          batch_size)
        neighbors = set(idx[1:])
        # parse the neighbors so that it does not contain points that are already in surface
        neighbors = neighbors.difference(surface)

        for current_neighbor in neighbors:
            # if angle_between(normals[seed_id], normals[n]) < angle_error_tolerance:
            if check_neighbor_condition(normals, coordinates, seed_id, current_neighbor, bounding_line,
                                        angle_error_tolerance):
                points_to_check.add(current_neighbor)
                surface.add(current_neighbor)
        counter += 1

    return list(surface)


class Scene:
    '''
    The driver for rendering a scene
    '''
    def __init__(self, canvas=None, view=None, marker=None, pcd=None, point_size=3.5):
        self.canvas = canvas # upper or lower canvas
        self.view = view # current view on the canvas
        self.marker = marker # the markers(points) of the current view
        self.pcd = pcd # the Open3D representation of the markers
        self.point_size = point_size # desired point size to be rendered

    def clear(self):
        '''
        clears the data inside this scene, but still have the canvas
        :return: True if the scene sucessfully cleared, raise error otherwise
        '''
        try:
            if self.view:
                self.canvas.central_widget.remove_widget(self.view)
            self.marker = None
            self.pcd = None
            self.view = None
            return True
        except:
            raise Scene.SceneError("Unable to clear")

    def render(self, pcd=None, camera_mode='turntable', point_size=0, auto_clear=True):
        '''
        Render the new pcd
        :param pcd: the new Open3D pcd data
        :param camera_mode: camera's mode
        :param point_size: each point's point size
        :param auto_clear: True if clear the scene before rendering, false otherwise
        :return:
        '''
        if auto_clear:
            self.clear()
        point_size = self.point_size if point_size == 0 else point_size
        try:
            self.pcd = pcd
            self.view = self.canvas.central_widget.add_view()
            self.view.parent = self.canvas.scene
            self.view.camera = camera_mode
            points = np.asarray(pcd.points)
            colors = np.asarray(pcd.colors)

            self.marker = visuals.Markers()
            self.marker.set_gl_state('translucent', blend=True, depth_test=True)
            self.marker.set_data(points, edge_color=colors, face_color=colors, size=point_size)
            self.view.add(self.marker)
            return True
        except:
            raise Scene.SceneError("Unable to render")

    class SceneError(Exception):
        pass


def prompt_saving():
    dialog = QDialog()
    form = QFormLayout(dialog)
    combo_box = QComboBox()
    combo_box.addItems(["Wall", "Floor", "Ceiling"])
    q_dialog_buttonbox = QDialogButtonBox()
    btn_ok = q_dialog_buttonbox.addButton(QDialogButtonBox.Ok)
    btn_cancel = q_dialog_buttonbox.addButton(QDialogButtonBox.Cancel)
    line_edit = QLineEdit()
    form.addRow(QLabel("Segment Name:"), line_edit)
    form.addRow(QLabel("Segmentation type:"), combo_box)
    form.addRow(q_dialog_buttonbox)

    def btn_ok_clicked():
        dialog.close()

    def btn_cancel_clicked():
        dialog.close()

    btn_ok.clicked.connect(btn_ok_clicked)

    btn_cancel.clicked.connect(btn_cancel_clicked)
    dialog.exec_()
    return {"type_class": combo_box.currentText(),
            "seg_name": line_edit.text()}

def prompt_deleting(segments):
    dialog = QDialog()
    form = QFormLayout(dialog)
    q_dialog_buttonbox = QDialogButtonBox()
    btn_ok = q_dialog_buttonbox.addButton(QDialogButtonBox.Ok)
    btn_cancel = q_dialog_buttonbox.addButton(QDialogButtonBox.Cancel)
    line_edit = QLineEdit()
    form.addRow(QLabel("Segment Name:"), line_edit)
    form.addRow(q_dialog_buttonbox)

    failed = False
    def btn_ok_clicked():
        nonlocal failed
        if line_edit.text() in segments:
            dialog.close()
        else:
            if not failed:
                failed = True
                form.addRow(QLabel("Invalid Segment Name"))

    def btn_cancel_clicked():
        dialog.close()

    btn_ok.clicked.connect(btn_ok_clicked)

    btn_cancel.clicked.connect(btn_cancel_clicked)
    dialog.exec_()
    return line_edit.text()