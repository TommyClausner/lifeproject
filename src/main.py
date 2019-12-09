from src.simulation import simulate_pop
from src.evolution import make_random_pop

motion_pattern_duration = 2  # in seconds
fps = 240  # frames per second
move_steps = motion_pattern_duration * fps

genomes = make_random_pop(num_inds=2, move_steps=move_steps)

new_genomes = simulate_pop(genomes, fps=fps)
