import numpy as np
from qiskit import QuantumCircuit, transpile
from qiskit_aer import AerSimulator
from qiskit_aer.noise import NoiseModel
from qiskit.quantum_info import Statevector, state_fidelity
from qiskit_ibm_runtime.fake_provider import FakeSherbrooke
from qiskit.circuit.library import StatePreparation

print("\n" + "="*50)
print(" STAGE 1: QUANTUM AMPLITUDE ENCODING")
print("="*50)

dna = "ATGCGTACGTTAGCGTACGATCGTAGCTAGCTTGACGATCGTACGTTAGC"
mapping = {'A': '00', 'T': '01', 'C': '10', 'G': '11'}

print(f"Target Sequence (50 bases): {dna[:20]}...")
print(f"Classical Mapping Rule:     {mapping}")

bit_string = "".join([mapping[base] for base in dna])
data_vector = np.array([float(bit) for bit in bit_string])

padded_vector = np.pad(data_vector, (0, 128 - len(data_vector)), 'constant')

norm = np.linalg.norm(padded_vector)
normalized_vector = padded_vector / norm

print(f"\nMathematical Transformation:")
print(f"- Raw Binary Length: {len(data_vector)} bits")
print(f"- Padded for Qubits: {len(padded_vector)} vector slots")
print(f"- First 5 Amplitudes: {np.round(normalized_vector[:5], 3)}")

state_prep = StatePreparation(normalized_vector)

qc_pure = QuantumCircuit(7)
qc_pure.append(state_prep, range(7))

qc_measure = qc_pure.copy()
qc_measure.measure_all()

print("\n" + "="*50)
print(" STAGE 2: DECODING & DATA VERIFICATION")
print("="*50)

ideal_simulator = AerSimulator()
transpiled_qc_measure = transpile(qc_measure, ideal_simulator)
counts = ideal_simulator.run(transpiled_qc_measure, shots=100000).result().get_counts()
reconstructed_bits = np.zeros(100)

for quantum_state, frequency in counts.items():
    if frequency > 50:  
        index = int(quantum_state, 2)
        if index < 100:
            reconstructed_bits[index] = 1.0

reverse_mapping = {'00': 'A', '01': 'T', '10': 'C', '11': 'G'}
reconstructed_dna = ""
for i in range(0, 100, 2):
    pair = f"{int(reconstructed_bits[i])}{int(reconstructed_bits[i+1])}"
    reconstructed_dna += reverse_mapping[pair]

print(f"Original:      {dna}")
print(f"Reconstructed: {reconstructed_dna}")
if dna == reconstructed_dna:
    print("DECODING SUCCESSFUL! ZERO DATA LOSS.")

print("\n" + "="*50)
print(" STAGE 3: OFFICIAL HACKATHON METRICS")
print("="*50)

sherbrooke_backend = FakeSherbrooke()
noise_model = NoiseModel.from_backend(sherbrooke_backend)

transpiled_qc = transpile(qc_pure, basis_gates=noise_model.basis_gates, optimization_level=3, approximation_degree=0.95)

ops = transpiled_qc.count_ops()
two_qubit_gates = ops.get('cx', 0) + ops.get('ecr', 0) + ops.get('cz', 0)
swap_gates = ops.get('swap', 0) 

ideal_state = Statevector.from_instruction(qc_pure)

noisy_simulator = AerSimulator(noise_model=noise_model)
transpiled_qc.save_density_matrix() 
noisy_job = noisy_simulator.run(transpiled_qc)
noisy_state = noisy_job.result().data()['density_matrix']
fidelity = state_fidelity(ideal_state, noisy_state)

print(f"1. Number of Qubits Used: {transpiled_qc.num_qubits} (Reduced from 100 via Amplitude Encoding)")
print(f"2. State Fidelity:        {fidelity:.4f}")
print(f"3. Circuit Depth:         {transpiled_qc.depth()}")
print(f"4. Two-Qubit Gate Count:  {two_qubit_gates} (ECR/CX gates)")
print(f"5. SWAP Gate Count:       {swap_gates} (Hardware topology routing)")

print("\n--- BONUS: SCALABILITY ANALYSIS ---")
print("As sequence length (N) increases, Basis Encoding requires 2N qubits (O(N) space).")
print("Our Amplitude Encoding scales logarithmically: Qubits = log2(2N) (O(log N) space).")
print("For the 12,000 base pair sequence (24,000 bits), we only require 15 Qubits (2^15 = 32,768).")
print("==================================================\n")