# Quantum DNA Compression

## Overview
This repository contains a hybrid quantum-classical pipeline designed to compress and encode a 50-base DNA sequence onto Noisy Intermediate-Scale Quantum (NISQ) hardware. The objective is to balance spatial compression (qubit count), circuit depth, and state fidelity.

## Methodology

The project evaluates four distinct approaches to data encoding, culminating in an optimized variational quantum state preparation architecture.

### 1. Classical Pre-Processing (Huffman Coding)
Analyzes the sequence entropy to establish a baseline for classical data compression before quantum encoding.

### 2. Exact Amplitude Encoding
Compresses 100 bits of classical data (50 bases) into logarithmic space using Qiskit's `StatePreparation`. While this achieves maximum spatial efficiency (7 logical qubits), transpilation requires deep circuits that are highly susceptible to hardware noise and decoherence, resulting in fidelity collapse.

### 3. Dense-Angle Batch Processing
Prioritizes hardware fidelity by utilizing a purely parallel Ry rotation architecture.
* **Advantage:** Achieves O(1) circuit depth with zero two-qubit entangling gates, yielding near-perfect state fidelity.
* **Limitation:** Requires spatial multiplexing (O(N) logical qubits), making it inefficient for scaling to massive DNA sequences.

### 4. Final Architecture: Variational 8-Qubit Encoding
The final methodology resolves the limitations of the previous approaches by treating quantum state preparation as a variational machine learning problem.
* **Spatial Compression:** Maps 50 DNA bases into exactly 8 logical qubits (6 address qubits, 2 data qubits).
* **Hardware-Efficient Ansatz:** Utilizes a parameterized circuit (`RealAmplitudes` or `EfficientSU2`) comprised strictly of hardware-native operations to minimize SWAP routing overhead.
* **Two-Phase Optimization:** Employs COBYLA for gradient-free global parameter search, followed by L-BFGS-B for precise local refinement.
* **Tunable Depth:** Circuit depth and ECR gate counts are strictly bounded by the defined ansatz repetitions, preventing the O(2^n) depth explosion inherent to exact state synthesis.

## Technical Metrics

The final variational pipeline is evaluated against the IBM `FakeSherbrooke` 127-qubit backend. Key outputs include:
* **Logical Qubits:** 8
* **Physical Footprint:** Dynamically mapped to the Sherbrooke topology via SABRE routing.
* **Two-Qubit Gates:** Constrained to the ansatz depth rather than dataset complexity.
* **State Fidelity:** Maximized for the selected hardware depth budget via the two-phase classical optimization loop.

https://drive.google.com/file/d/1MlhVrO0dQFIi_nFcwJ1V7XCc1VPQz7Yq/view?usp=sharing (Video Link)

## Setup and Execution

**1. Install Dependencies**
```bash
pip install qiskit qiskit-aer qiskit-ibm-runtime numpy scipy matplotlib

python variational_8qubit.py --reps=10 --maxiter=8000 --restarts=5

python batch_angle_encoding_25q.py

python amplitude_encoding_7q.py
