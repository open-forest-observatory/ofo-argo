# Argo Workflow

This repository contains [Argo Workflows](https://argoproj.github.io/workflows) used by the **Open Forest Observatory (OFO)**. It is being developed to run the [automate-metashape[(https://github.com/open-forest-observatory/automate-metashape) pipeline simultaneously across multiple virtual machines on Jetstream2 Cloud. This type of scaling would enable us to process many photogrammetry projects simultaneously (instead of sequentially) and vastly reduce total processing time. Argo is meant to work on Kubernetes which orchestrates containers (ie, automate-metashape in docker), scales the processing to multiple VMs, and balances to load between the VMs. 

---



---

## Setup & Usage

To get started or deploy workflows, refer to the detailed setup and usage guide:

[OFO Workflow Setup & Usage Documentation](https://docs.google.com/document/d/1ukaNrnbM4VINZeIyPb7z0lAMLhismMPMBCLoMxAaa30/edit?usp=sharing)
