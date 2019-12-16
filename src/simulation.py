import pybullet as p
from src.individual import _move_individual, _make_random_genome, _get_pos, \
    _compute_mass
from src.evolution import fitness
import time
import numpy as np
from matplotlib import cm
import multiprocessing as mp


def connect_to_servers(cores):
    # connect to multiple servers according to the amount of CPU cores requested
    sim_ids = []
    for simulation in range(cores):
        sim_ids.append(_make_sim_env('direct'))
    return sim_ids


def reset_simulation(pop, sim_id):
    # remove all bodies and reset simulation
    [p.removeBody(ind, physicsClientId=sim_id) for ind in pop]
    p.resetSimulation(physicsClientId=sim_id)
    p.disconnect(physicsClientId=sim_id)


def simulate_multi_core(gene_pool, evo_config, track_individuals=True, num_cores=1, sim_ids=None):
    # perform simulation using multiprocessing library (on multiple CPU cores) by splitting the amount of individuals
    # into as many chunks as CPU cores were requested
    def worker(ind, p_gene_pool, e_conf, sim_id, q):
        pop, sim_id, tracker = simulate_pop(p_gene_pool.tolist(), e_conf,
                                            track_individuals=track_individuals, direct=True, sim_id=sim_id)
        q.put((ind, fitness(pop, sim_id), tracker))
        reset_simulation(pop, sim_id)

    split_gene_pool = np.array_split(np.array(gene_pool), num_cores)

    if sim_ids is None:
        sim_ids = []
        for simulation in range(num_cores):
            sim_ids.append(_make_sim_env('direct'))

    qout = mp.Queue(maxsize=-1)
    processes = [mp.Process(target=worker, args=(ind, data_in[0], evo_config, data_in[1], qout))
                 for ind, data_in in enumerate(zip(split_gene_pool, sim_ids))]

    for process in processes:
        process.start()

    unsorted_result = []
    while any(process.is_alive() for process in processes):
        while not qout.empty():
            unsorted_result.append(qout.get(False))

    sorted_fitness = [t[1] for t in sorted(unsorted_result)]
    sorted_tracker = [t[2] for t in sorted(unsorted_result)]

    fitness_all = []
    for sub_pop in sorted_fitness:
        fitness_all += sub_pop

    tracker_all = {}
    counter = 0
    for sub_pop in sorted_tracker:
        for key in sub_pop.keys():
            tracker_all[counter] = sub_pop[key]
            counter += 1

    return fitness_all, tracker_all


def simulate_pop(gene_pool, evo_config, args=None, direct=False, track_individuals=True, sim_id=None):
    # simulate all individuals of one generation
    if sim_id is None:
        if direct:
            sim_id = _make_sim_env('direct')
        else:
            sim_id = _make_sim_env('gui')

    pop = [_genome2simulation(sim_id, evo_config, genome) for genome in gene_pool]
    _disable_collision(sim_id, pop)

    # simulate
    duration_steps = evo_config['simulation']['fps'] * evo_config['simulation']['duration']
    if duration_steps < 0:
        duration_steps = np.Inf

    step = 0
    if args is not None:
        slow_factor = args.slow_down_factor
    else:
        slow_factor = 1

    ind_tracker = {}
    while p.isConnected(sim_id) and step < duration_steps:
        p.stepSimulation(physicsClientId=sim_id)

        for indiv, genome in zip(pop, gene_pool):
            _move_individual(indiv, genome, step, evo_config, sim_id)
            if track_individuals and step % 10 == 0:
                x, y = _get_pos(indiv, sim_id)
                if indiv in ind_tracker.keys():
                    ind_tracker[indiv].append([x, y])
                else:
                    ind_tracker[indiv] = [[x, y]]
                    
        if args is not None:
            if args.follow_target:
                target = p.getBasePositionAndOrientation(indiv, physicsClientId=sim_id)[0][0:3]
                p.resetDebugVisualizerCamera(cameraDistance=15, cameraYaw=30, cameraPitch=-52, cameraTargetPosition=target)

        if not direct:
            time.sleep(1. / evo_config['simulation']['fps'] * slow_factor)
        step += 1
    return pop, sim_id, ind_tracker


def _make_sim_env(gui_or_direct):
    # make simulation environment
    if gui_or_direct.lower() == 'gui':
        sim_id = p.connect(p.GUI)
    else:
        sim_id = p.connect(p.DIRECT)

    p.setGravity(0, 0, -9.81, physicsClientId=sim_id)
    p.createMultiBody(0, p.createCollisionShape(p.GEOM_PLANE, physicsClientId=sim_id), physicsClientId=sim_id)
    return sim_id


def _get_start_height(genome):
    # get z coordinate for each body part
    height = 0
    for key in genome[0].keys():
        if (genome[0][key][2] * 2) > height:
            height = genome[0][key][2] * 2
    return height + 0.1


def _make_mb_dict():
    # setup base dictionary for multi body
    return {'link_masses': [],
            'link_col_shape_ids': [],
            'link_vis_shape_ids': [],
            'link_pos': [],
            'link_ori': [[0, 0, 0, 1], [1, 0, 0, 1], [-1, 0, 0, 1], [0, 0, 0, 1], [0, 0, 0, 1], [0, 0, 0, -1],
                         [1, 0, 0, 1],
                         [1, 0, 0, -1], [0, 0, 0, 1], [0, 0, 0, -1], [1, 0, 0, 1], [1, 0, 0, -1], [0, 0, 0, 1],
                         [0, 0, 0, 1],
                         [0, 0, 0, 1], [0, 0, 0, 1]],
            'link_iner_frame_pos': [[0, 0, 0]] * 16,
            'link_iner_frame_ori': [[0, 0, 0, 1]] * 16,
            'inds': [0, 1, 2, 3, 1, 1, 5, 6, 4, 4, 9, 10, 7, 8, 11, 12],
            'joint_types': [p.JOINT_FIXED, p.JOINT_REVOLUTE, p.JOINT_REVOLUTE, p.JOINT_FIXED, p.JOINT_REVOLUTE,
                            p.JOINT_REVOLUTE, p.JOINT_REVOLUTE, p.JOINT_REVOLUTE, p.JOINT_REVOLUTE, p.JOINT_REVOLUTE,
                            p.JOINT_REVOLUTE, p.JOINT_REVOLUTE, p.JOINT_FIXED, p.JOINT_FIXED, p.JOINT_FIXED,
                            p.JOINT_FIXED],
            'axis': [[0, 0, 1]] * 16}


def _get_random_color(evo_config):
    c_map = cm.get_cmap(evo_config['simulation']['colormap'], 255)(np.linspace(0, 1, 255))
    return c_map[np.random.random_integers(0, 254, 1)].tolist()[0]


def _genome2multi_body_data(sim_id, evo_config, genome=({}, {})):
    # create multi body data from genome
    if not bool(genome[0]):
        genome = _make_random_genome(evo_config)

    col_box_ids = {}
    vis_box_ids = {}
    box_color = _get_random_color(evo_config)
    sphere_color = [sphere_color * 0.5 for sphere_color in box_color[:-1]] + [1]
    # generate visual/ collision shape ids for objects with 'new' sizes
    for limb in genome[0].keys():
        col_box_ids[limb] = p.createCollisionShape(p.GEOM_BOX, halfExtents=genome[0][limb], physicsClientId=sim_id)
        vis_box_ids[limb] = p.createVisualShape(p.GEOM_BOX, halfExtents=genome[0][limb],
                                                rgbaColor=box_color, physicsClientId=sim_id)

    # for all spheres connected to the chest take z value of chest box as radius
    vis_sphere_id_chest = p.createVisualShape(p.GEOM_SPHERE, radius=genome[0]['chest'][2],
                                              rgbaColor=sphere_color, physicsClientId=sim_id)
    col_sphere_id_chest = p.createCollisionShape(p.GEOM_SPHERE, radius=genome[0]['chest'][2], physicsClientId=sim_id)
    # analog for hip
    vis_sphere_id_hip = p.createVisualShape(p.GEOM_SPHERE, radius=genome[0]['hip'][2], rgbaColor=sphere_color,
                                            physicsClientId=sim_id)
    col_sphere_id_hip = p.createCollisionShape(p.GEOM_SPHERE, radius=genome[0]['hip'][2], physicsClientId=sim_id)

    # fill multi body parameter values
    mb = _make_mb_dict()

    mb['start_height'] = _get_start_height(genome)

    mb['link_masses'] = [_compute_mass(genome[0]['chest'], evo_config),
                         _compute_mass(genome[0]['chest'][2], evo_config),
                         _compute_mass(genome[0]['chest'][2], evo_config),
                         _compute_mass(genome[0]['hip'], evo_config)] + \
                        [_compute_mass(genome[0]['chest'][2], evo_config)] * 4 + \
                        [_compute_mass(genome[0]['hip'][2], evo_config)] * 4 + \
                        [_compute_mass(genome[0]['left_hand'], evo_config),
                         _compute_mass(genome[0]['right_hand'], evo_config),
                         _compute_mass(genome[0]['left_foot'], evo_config),
                         _compute_mass(genome[0]['right_foot'], evo_config)]

    mb['link_col_shape_ids'] = [col_box_ids['chest'],
                                col_sphere_id_chest,
                                col_sphere_id_chest,
                                col_box_ids['hip']] + \
                               [col_sphere_id_chest] * 4 + \
                               [col_sphere_id_hip] * 4 + \
                               [col_box_ids['left_hand'],
                                col_box_ids['right_hand'],
                                col_box_ids['left_foot'],
                                col_box_ids['right_foot']]

    mb['link_vis_shape_ids'] = [vis_box_ids['chest'],
                                vis_sphere_id_chest,
                                vis_sphere_id_chest,
                                vis_box_ids['hip']] + \
                               [vis_sphere_id_chest] * 4 + \
                               [vis_sphere_id_hip] * 4 + \
                               [vis_box_ids['left_hand'],
                                vis_box_ids['right_hand'],
                                vis_box_ids['left_foot'],
                                vis_box_ids['right_foot']]

    mb['link_pos'] = [[0, genome[0]['chest'][1] + genome[0]['chest'][2], 0],
                      [0, genome[0]['chest'][1] + genome[0]['chest'][2], 0],
                      [0, 0, 0],
                      [0, genome[0]['chest'][2] + genome[0]['hip'][1], 0],
                      [-genome[0]['chest'][0] - genome[0]['chest'][2], 0, 0],
                      [genome[0]['chest'][0] + genome[0]['chest'][2], 0, 0],
                      [0, 0, 0],
                      [0, 0, 0],
                      [-genome[0]['hip'][0] - genome[0]['hip'][2], 0, 0],
                      [genome[0]['hip'][0] + genome[0]['hip'][2], 0, 0],
                      [0, 0, 0],
                      [0, 0, 0],
                      [-genome[0]['left_hand'][0] - genome[0]['chest'][2], 0, 0],
                      [genome[0]['right_hand'][0] + genome[0]['chest'][2], 0, 0],
                      [-genome[0]['left_foot'][0] - genome[0]['hip'][2], 0, 0],
                      [genome[0]['right_foot'][0] + genome[0]['hip'][2], 0, 0],
                      ]

    return mb, col_sphere_id_chest, vis_sphere_id_chest


def _genome2simulation(sim_id, evo_config, genome=({}, {})):
    # transform genome to simulatable multi body (or create new random genome and transform)
    if not bool(genome[0]):
        mb_data = _genome2multi_body_data(sim_id, evo_config)
    else:
        mb_data = _genome2multi_body_data(sim_id, evo_config, genome)

    mb = mb_data[0]

    return p.createMultiBody(np.mean(mb['link_masses']),
                             mb_data[1],
                             mb_data[2],
                             [0, 0, mb['start_height']],
                             [0, 0, 0, 1],
                             linkMasses=mb['link_masses'],
                             linkCollisionShapeIndices=mb['link_col_shape_ids'],
                             linkVisualShapeIndices=mb['link_vis_shape_ids'],
                             linkPositions=mb['link_pos'],
                             linkOrientations=mb['link_ori'],
                             linkInertialFramePositions=mb['link_iner_frame_pos'],
                             linkInertialFrameOrientations=mb['link_iner_frame_ori'],
                             linkParentIndices=mb['inds'],
                             linkJointTypes=mb['joint_types'],
                             linkJointAxis=mb['axis'],
                             useMaximalCoordinates=False,
                             physicsClientId=sim_id)


def _disable_collision(sim_id, pop):
    # disable collision between each joint in individual i and each joint in individual j
    for idx, individual in enumerate(pop[:-1]):  # from first to second last
        for other_individual in pop[idx + 1:]:  # from next (relative to above) to end

            # pair all link indices and disable collision (num of joints = num of links)
            for joint in range(-1, p.getNumJoints(individual, physicsClientId=sim_id)):  # all joints to ...
                for other_joint in range(-1, p.getNumJoints(other_individual,
                                                            physicsClientId=sim_id)):  # ... all other joints
                    p.setCollisionFilterPair(individual, other_individual, joint, other_joint, 0,
                                             physicsClientId=sim_id)
