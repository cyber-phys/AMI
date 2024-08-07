import redis
import time
import json
import numpy as np  # Import numpy for array manipulations
import matplotlib.pyplot as plt  # Import matplotlib for plotting
from mpl_toolkits.mplot3d import Axes3D  # Import module for 3D plotting
from scipy.interpolate import griddata  # Import griddata for interpolation
from scipy.spatial import Delaunay
from scipy.optimize import minimize

r = redis.Redis(host='localhost', port=6379, db=0)

queue_name = 'matlab_data'
def generate_crochet_pattern(vertices, faces, distances):
    """
    Generate crochet pattern instructions from 3D mesh data.
    """
    instructions = []
    seed_vertex = int(np.argmin(distances))  # Convert NumPy int64 to native int
    max_vertex = int(np.argmax(distances))
    row_edges = []
    col_edges = []
    S = [[]]

    # Step 1: Select seed and calculate geodesic distances (already done)
    # Step 2: Iterate vertices and create rows of stitches
    for i, vertex in enumerate(vertices):
        stitch = {
            'vertex_index': int(i),  # Convert NumPy int64 to native int
            'position': vertex.tolist(),
            'distance': float(distances[i])  # Convert NumPy float to native float
        }
        if i > 0:
            row_edges.append((int(i - 1), int(i)))  # Convert NumPy int64 to native int
        instructions.append(stitch)

    # Step 3: Form columns (inter-row connections)
    for start, end in zip(row_edges[:-1], row_edges[1:]):
        col_edges.append((int(start[1]), int(end[0])))  # Convert NumPy int64 to native int

    # Combine into instructions
    pattern = {
        'seed_vertex': seed_vertex,
        'row_edges': row_edges,
        'col_edges': col_edges,
        'stitches': instructions
    }
    return pattern


def find_row_order(vertices, faces, distances, w):
    # Calculate isolines based on the geodesic distances and yarn width w
    max_distance = np.max(distances)
    isoline_values = np.arange(0, max_distance, w)
    row_order = []

    for isoline_value in isoline_values:
        # Find vertices that are close to the current isoline value
        close_vertices = vertices[np.abs(distances - isoline_value) < w / 2]
        row = [
            {
                'vert_index': int(i),  # Convert NumPy int64 to native int
                'raw_distance': float(distances[i]),  # Convert NumPy float to native float
                'reg_distance': isoline_value
            }
            for i, vertex in enumerate(vertices)
            if np.abs(distances[i] - isoline_value) < w / 2
        ]
        row_order.append(row)

    return row_order


#Chatgpt code
def compute_gradient(vertices, values):
    """Compute the gradient of the scalar field 'values' defined on the mesh vertices."""
    gradients = np.zeros_like(vertices)
    for i, v in enumerate(vertices):
        # For simplicity, using finite differences (this can be replaced with more accurate methods)
        neighbors = np.where(np.linalg.norm(vertices - v, axis=1) < 1e-5)[0]
        if len(neighbors) > 1:
            deltas = vertices[neighbors] - v
            value_deltas = values[neighbors] - values[i]
            gradients[i] = np.mean(value_deltas[:, np.newaxis] * deltas, axis=0)
    return gradients

def rotated_gradient(gradients):
    """Rotate the gradient vectors by 90 degrees in the tangent plane."""
    J = np.array([[0, -1], [1, 0]])  # Rotation matrix for 2D case
    return np.dot(gradients[:, :2], J.T)

def objective(g, vertices, gradients, rotated_gradients):
    """Objective function to minimize."""
    diff = np.einsum('ij,ij->i', gradients, np.gradient(g, vertices[:, :2], axis=0)) - 1
    return np.sum(diff**2)

def find_column_order(vertices, f_values, boundary_indices):
    """Find the column order 'g' given the vertices, f_values, and boundary condition."""
    gradients = compute_gradient(vertices, f_values)
    rotated_gradients = rotated_gradient(gradients)

    # Initial guess for g (could be zeros or any other initial guess)
    g_initial = np.zeros(len(vertices))

    # Boundary condition
    g_initial[boundary_indices] = 0

    # Minimize the objective function
    result = minimize(objective, g_initial, args=(vertices, gradients, rotated_gradients), method='L-BFGS-B')
    return result.x

while True:
    item = r.lpop(queue_name)
    if item:
        data = json.loads(item.decode('utf-8'))
        vertices = np.array(data['vertices'])
        faces = np.array(data['faces'])
        distances = np.array(data['u_vfaOut'])

        row_order = find_row_order(vertices, faces, distances, 0.03)

        # Create a 3D plot outside of the function
        fig = plt.figure()
        ax = fig.add_subplot(111, projection='3d')
        ax.azim = 90  # Rotate the plot to match the desired view
        ax.elev = -90
        ax.roll = 45

        # Plotting the isolines
        for close_vertices in row_order:
            vertices_to_plot = np.array([vertices[item['vert_index']] for item in close_vertices])
            ax.scatter(vertices_to_plot[:, 0], vertices_to_plot[:, 1], vertices_to_plot[:, 2], s=1)

        # Find column order for each row of isoline vertices
        column_orders = []
        for close_vertices in row_order:
            if len(close_vertices) > 1:
                f_values = np.array([item['raw_distance'] for item in close_vertices])
                row_vertices = np.array([vertices[item['vert_index']] for item in close_vertices])
                boundary_indices = [0]  # Example boundary index, replace with actual boundary condition
                g_values = find_column_order(row_vertices, f_values, boundary_indices)
                print(g_values)
                column_orders.append(g_values)

        # # Generate crochet pattern from vertices and distances
        instructions = generate_crochet_pattern(vertices, faces, distances)
        # print(f"Crochet Instructions: {json.dumps(instructions, indent=2)}")
        with open('crochet_instructions.json', 'w') as f:
            json.dump(instructions, f, indent=2)

        plt.show()
        print(f"Processed data item from the queue.")
    else:
        print("Queue is empty, waiting for new items...")
        time.sleep(2)  # Wait for 2 seconds before checking again
