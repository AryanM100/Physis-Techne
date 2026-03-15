#!/usr/bin/env python3
import math
import sys
import time
from collections import defaultdict, Counter
from pathlib import Path

import numpy as np
from scipy.optimize import minimize

from qiskit import QuantumCircuit, transpile
from qiskit.circuit.library import RealAmplitudes
from qiskit_aer import AerSimulator
from qiskit_aer.noise import NoiseModel
from qiskit.quantum_info import Statevector, DensityMatrix, state_fidelity
from qiskit_ibm_runtime.fake_provider import FakeSherbrooke

BASE_TO_CODE = {"A": 0b00, "T": 0b01, "C": 0b10, "G": 0b11}
CODE_TO_BASE = {"00": "A", "01": "T", "10": "C", "11": "G"}
PHYSICAL_GATES = ["ecr", "id", "rz", "sx", "x"]
DEFAULT_DNA_50 = "ATGCGTACGTTAGCGTACGATCGTAGCTAGCTTGACGATCGTACGTTAGC"


def pad_to_power_of_2(dna):
    n = len(dna)
    target = 1
    while target < n:
        target <<= 1
    return dna.ljust(target, "A"), target


def build_target_statevector(dna_padded, addr_qubits):
    total_qubits = addr_qubits + 2
    dim = 2 ** total_qubits
    vec = np.zeros(dim, dtype=complex)
    amp = 1.0 / np.sqrt(len(dna_padded))
    for addr, base in enumerate(dna_padded):
        base_code = BASE_TO_CODE[base]
        idx = addr | (base_code << addr_qubits)
        vec[idx] = amp
    return Statevector(vec)


def build_ansatz(n_qubits=8, reps=10):
    try:
        from qiskit.circuit.library import real_amplitudes
        return real_amplitudes(n_qubits, reps=reps, entanglement="linear")
    except ImportError:
        return RealAmplitudes(n_qubits, reps=reps, entanglement="linear")


def cost_function(params, ansatz, target_data):
    bound_circ = ansatz.assign_parameters(params)
    trial_sv = Statevector.from_instruction(bound_circ)
    fid = abs(np.vdot(target_data, trial_sv.data)) ** 2
    return 1.0 - fid


def optimize_circuit(target_sv, n_qubits=8, reps=10, maxiter=5000,
                     num_restarts=3, refine=True):
    """Two-phase optimization: COBYLA (explore) -> L-BFGS-B (refine)."""
    ansatz = build_ansatz(n_qubits, reps)
    n_params = ansatz.num_parameters
    cx_per_rep = n_qubits - 1

    print(f"  Ansatz: RealAmplitudes, {reps} reps, linear entanglement")
    print(f"  Parameters: {n_params}")
    print(f"  CX per rep: {cx_per_rep}, Total CX: {cx_per_rep * reps}")

    target_data = target_sv.data
    best_cost = 1.0
    best_params = None

    print(f"\n  Phase 1: COBYLA ({num_restarts} restarts, {maxiter} iters each)")
    for restart in range(num_restarts):
        t0 = time.time()
        x0 = np.random.randn(n_params) * 0.5
        result = minimize(
            cost_function, x0, args=(ansatz, target_data),
            method="COBYLA",
            options={"maxiter": maxiter, "rhobeg": 0.5},
        )
        elapsed = time.time() - t0
        fid = 1 - result.fun
        tag = " << BEST" if result.fun < best_cost else ""
        print(f"    Restart {restart+1}/{num_restarts}: fidelity={fid:.6f} "
              f"({elapsed:.1f}s){tag}")
        if result.fun < best_cost:
            best_cost = result.fun
            best_params = result.x.copy()

    if refine and best_params is not None:
        print(f"\n  Phase 2: L-BFGS-B refinement (starting from best COBYLA)")
        t0 = time.time()
        result2 = minimize(
            cost_function, best_params, args=(ansatz, target_data),
            method="L-BFGS-B",
            options={"maxiter": maxiter, "ftol": 1e-12},
        )
        elapsed = time.time() - t0
        fid2 = 1 - result2.fun
        if result2.fun < best_cost:
            best_cost = result2.fun
            best_params = result2.x.copy()
            print(f"    Refined: fidelity={fid2:.6f} ({elapsed:.1f}s) << IMPROVED")
        else:
            print(f"    Refined: fidelity={fid2:.6f} ({elapsed:.1f}s) (no improvement)")

    return ansatz, best_params, 1.0 - best_cost


def strip_delays(circ):
    out = QuantumCircuit(*circ.qregs, *circ.cregs, name=f"{circ.name}_clean")
    out.global_phase = circ.global_phase
    for item in circ.data:
        if item.operation.name != "delay":
            out.append(item.operation, item.qubits, item.clbits)
    return out


def decode_counts(counts, seq_len, total_qubits, addr_qubits):
    per_addr = defaultdict(Counter)
    for state, freq in counts.items():
        bits = state.replace(" ", "")
        if len(bits) < total_qubits:
            bits = bits.zfill(total_qubits)
        elif len(bits) > total_qubits:
            bits = bits[-total_qubits:]
        base_bits = bits[:2]
        addr_bits = bits[2:]
        addr = int(addr_bits, 2)
        if addr >= seq_len:
            continue
        base = CODE_TO_BASE.get(base_bits)
        if base:
            per_addr[addr][base] += freq
    return "".join(
        per_addr[i].most_common(1)[0][0] if per_addr[i] else "?"
        for i in range(seq_len)
    )


def run_experiment(dna, reps=10, maxiter=5000, num_restarts=3,
                   shots=20000, refine=True):
    t0_total = time.time()

    dna_padded, padded_len = pad_to_power_of_2(dna)
    addr_qubits = int(math.log2(padded_len))
    total_qubits = addr_qubits + 2

    print("=" * 60)
    print("  VARIATIONAL DNA ENCODING (OPTIMIZED)")
    print("=" * 60)
    print(f"DNA length          : {len(dna)}")
    print(f"Padded to           : {padded_len} (2^{addr_qubits})")
    print(f"Total logical qubits: {total_qubits}")
    print(f"Qubit reduction     : {100*(1 - total_qubits/(2*len(dna))):.1f}%")

    target_sv = build_target_statevector(dna_padded, addr_qubits)

    print(f"\n--- OPTIMIZATION (reps={reps}) ---")
    ansatz, best_params, train_fidelity = optimize_circuit(
        target_sv, total_qubits, reps, maxiter, num_restarts, refine
    )

    opt_circ = ansatz.assign_parameters(best_params)
    opt_circ.name = "variational_dna"

    # Compact metrics
    prep_basis = transpile(opt_circ, basis_gates=PHYSICAL_GATES, optimization_level=3)
    prep_basis = strip_delays(prep_basis)
    compact_ops = dict(prep_basis.count_ops())
    compact_ecr = compact_ops.get("ecr", 0)

    print(f"\n--- COMPACT CIRCUIT ---")
    print(f"Qubits: {prep_basis.num_qubits}  Depth: {prep_basis.depth()}  "
          f"ECR: {compact_ecr}")

    # FakeSherbrooke
    backend = FakeSherbrooke()
    noise_model = NoiseModel.from_backend(backend)

    prep_t = transpile(opt_circ, backend=backend, optimization_level=3)
    prep_t_ops = dict(prep_t.count_ops())
    swap_count = prep_t_ops.get("swap", 0)

    print(f"\n--- FAKESHERBROOKE ---")
    print(f"Physical qubits: {prep_t.num_qubits}  "
          f"Depth: {prep_t.depth()}  ECR: {prep_t_ops.get('ecr',0)}  "
          f"SWAP: {swap_count}")

    # Noisy fidelity
    ideal_state = Statevector.from_instruction(prep_basis)
    prep_dm = prep_basis.copy()
    prep_dm.save_density_matrix()
    noisy_sim = AerSimulator(method="density_matrix", noise_model=noise_model)
    noisy_result = noisy_sim.run(prep_dm).result()
    noisy_dm = DensityMatrix(noisy_result.data(0)["density_matrix"])
    noisy_fidelity = state_fidelity(ideal_state, noisy_dm)

    print(f"\n  >> TRAINING FIDELITY: {train_fidelity:.6f}")
    print(f"  >> NOISY FIDELITY:   {noisy_fidelity:.6f}")

    # Decoding
    meas_circ = opt_circ.copy()
    meas_circ.measure_all()
    meas_t = transpile(meas_circ, backend=backend, optimization_level=3)
    ideal_sim = AerSimulator()
    ideal_counts = ideal_sim.run(meas_t, shots=shots).result().get_counts()
    recovered = decode_counts(ideal_counts, len(dna), total_qubits, addr_qubits)
    matches = sum(a == b for a, b in zip(dna, recovered))
    acc = matches / len(dna)

    print(f"\n--- DECODING ---")
    if len(dna) <= 100:
        print(f"Original : {dna}")
        print(f"Recovered: {recovered}")
    print(f"Accuracy : {matches}/{len(dna)} = {acc:.4f}")

    elapsed = time.time() - t0_total

    print("\n" + "=" * 60)
    print("  SUMMARY FOR JUDGES")
    print("=" * 60)
    print(f"Logical Qubits   : {total_qubits}")
    print(f"Physical Qubits  : {prep_t.num_qubits} (FakeSherbrooke)")
    print(f"Circuit Depth    : {prep_basis.depth()}")
    print(f"Two-Qubit Gates  : {compact_ecr} ECR")
    print(f"SWAP Gates       : {swap_count}")
    print(f"State Fidelity   : {noisy_fidelity:.4f}")
    print(f"DNA Recovery     : {acc:.4f}")
    print(f"Total Run Time   : {elapsed:.2f}s")


def main():
    dna = DEFAULT_DNA_50
    reps = 10
    maxiter = 5000
    restarts = 3
    no_refine = False

    for arg in sys.argv[1:]:
        if arg.startswith("--reps="):
            reps = int(arg.split("=")[1])
        elif arg.startswith("--maxiter="):
            maxiter = int(arg.split("=")[1])
        elif arg.startswith("--restarts="):
            restarts = int(arg.split("=")[1])
        elif arg == "--no-refine":
            no_refine = True
        elif arg == "--12k":
            seq_file = Path(__file__).parent / "12k"
            if seq_file.exists():
                raw = seq_file.read_text().replace("\n", "").strip().upper()
                dna = "".join(c for c in raw if c in "ATCG")
                print(f"Loaded 12K sequence: {len(dna)} bases")
            else:
                print("ERROR: 12k file not found!")
                return

    run_experiment(dna, reps=reps, maxiter=maxiter,
                   num_restarts=restarts, refine=not no_refine)


if __name__ == "__main__":
    main()
