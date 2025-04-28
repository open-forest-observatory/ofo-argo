# ofo-data-pipeline

This repository contains data workflows used by the **Open Forest Observatory (OFO)**. Currently, it is designed to run the `automate-metashape` pipeline, with more workflows to be added in the future.

---

## Argo Workflows Integration

We use **Argo Workflows** to orchestrate and manage the execution of OFO workflows. Argo provides:

- A **Kubernetes-native** interface to define and execute workflows as DAGs.
- **Scalable** and **fault-tolerant** execution of tasks.
- Built-in support for **artifact passing**, **parameterization**, and **retries**.
- Ideal management of complex, containerized pipelines—like those used in OFO's data processing stack.

---

## Setup & Usage

To get started or deploy workflows, refer to the detailed setup and usage guide:

[OFO Workflow Setup & Usage Documentation](https://docs.google.com/document/d/1ukaNrnbM4VINZeIyPb7z0lAMLhismMPMBCLoMxAaa30/edit?usp=sharing)
