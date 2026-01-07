This folder contains files used in configuring the Kubernetes cluster that will run Argo.

- `gpu-taint-rule.yaml` - NodeFeatureRule that automatically taints GPU nodes to prevent CPU workloads from scheduling on them. See [cluster creation docs](../../docs/admin/cluster-creation-and-resizing.md#configure-gpu-node-tainting) for deployment instructions.
- `mig-nodegroup-labels.yaml` - NodeFeatureRule that configures MIG partitioning based on nodegroup naming convention. Nodegroups with `mig1-`, `mig2-`, or `mig3-` in the name are automatically configured with corresponding MIG profiles. See [MIG configuration docs](../../docs/admin/cluster-creation-and-resizing.md#configure-mig-multi-instance-gpu) for details.
- `manila-cephfs-csi-config2.yaml` - Manila CephFS CSI configuration for shared storage.
- `manila-test-pod2.yaml` - Test pod for verifying Manila share mounting.