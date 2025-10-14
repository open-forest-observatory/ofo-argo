## One-time local machine software setup

Make sure your local system has the necessary tools, and first make sure you’re in the right venv called openstack (created in the cluster creation guide). Additionally, we need OpenStack app credentials to look up the parameters of our Manila share based on its name. An alternative is to look these up from some other existing source (e.g. Horizon UI) and provide them manually, in which case the openstack system tools are not necessary.

| `source ~/venv/openstack/bin/activate` `source ~/.ofocluster/app-cred-ofocluster-openrc.sh` `pip install -U python-manilaclient sudo apt install -y jq` sudo snap install helm –classic |
| :---- |

If returning to this after a reboot, and you know you already have the necessary tools, you still need to source the right OpenStack env and application credentials.

`source ~/venv/openstack/bin/activate`  
`source ~/.ofocluster/app-cred-ofocluster-openrc.sh`

## Install the Ceph CSI driver on the cluster using Helm

| helm repo add ceph-csi https://ceph.github.io/csi-chartshelm repo updatekubectl create namespace ceph-csi-cephfshelm install \--namespace "ceph-csi-cephfs" "ceph-csi-cephfs" ceph-csi/ceph-csi-cephfshelm status \--namespace "ceph-csi-cephfs" "ceph-csi-cephfs"  Look up the necessary identifiers of the desired share Based on the share name and access rule name that we want to mount, query OpenStack to look up the MANILA\_ROOT\_PATH, MANILA\_ACCESS\_RULE, and MANILA\_ACCESS KEY, and set them so that we can sub them into the K8s Manila config when we apply it. The config requires these values. MANILA\_SHARE\_NAME=dytest3 export MANILA\_ACCESS\_RULE\_NAME=dytest3-rw \# A json-formatted list of Manila monitors to sub into the ConfigMap export MANILA\_MONITORS\_JSON=$(openstack share export location list "$MANILA\_SHARE\_NAME" \-f json | jq \-r '.\[0\].Path | split(":/")\[0\] | split(",") | map("\\"" \+ . \+ "\\"") | join(",")') \# The root path to the manila share export MANILA\_ROOT\_PATH=$(openstack share export location list $MANILA\_SHARE\_NAME \-f json | jq \-r '.\[0\].Path' | awk \-F':/' '{print "/"$2}') \# The ID for the named access rule (needed to look up the key) ACCESS\_RULE\_ID=$(openstack share access list "$MANILA\_SHARE\_NAME" \-f json | jq \-r ".\[\] | select(.\\"Access To\\" \== \\"$MANILA\_ACCESS\_RULE\_NAME\\") | .ID") \# The secret key for the access rule export MANILA\_ACCESS\_KEY=$(openstack share access list "$MANILA\_SHARE\_NAME" \-f json | jq \-r ".\[\] | select(.\\"Access To\\" \== \\"$MANILA\_ACCESS\_RULE\_NAME\\") | .\\"Access Key\\"")  \# Confirm we extracted the attributes we expected, which we need for the next step. echo $MANILA\_MONITORS\_JSON echo $MANILA\_ROOT\_PATH echo $MANILA\_ACCESS\_RULE\_NAME echo $MANILA\_ACCESS\_KEY \# As an alternative, you can look these up on Horizon  Apply the share config to the cluster  There is a “template” for the kubernetes config file that you will apply to add the share to the cluster. It is a normal kubernetes config yaml file, except is has several parameters unspecified, instead represented by variables such as \`${MANILA\_ACCESS\_RULE\_NAME} \`. These are the variables we prepared in the previous step. The following command will substitute the env vars we previously prepared into the K8s csi config yaml file and then apply it to the cluster. (It is done all in one step so we don’t save this file, which contains secrets, to disk. Note that the namespaces of the various resources to be created are defined within the yaml, so \-n does not have to be used here. But if namespaces are ever to change, we need to update the config yaml. Clone the ofo-argo repo to get the K8s config to apply `cd ~/repos git clone https://github.com/open-forest-observatory/ofo-argo cd ofo-argo`  OR, pull from existing repo `cd ~/repos/ofo-argo git pull`  \# Create the namespace that will contain the PVC we will apply below (as well as the whole argo app, described in the next guide)kubectl create namespace argo envsubst \< k8s-setup/manila-cephfs-csi-conifg.yaml | kubectl apply \-f \-kubectl describe secret \-n ceph-csi-cephfs manila-share\-secretkubectl describe persistentvolume ceph-share-rw-pvkubectl describe \-n argo persistentvolumeclaim ceph-share-rw-pvc |
| :---- |

To delete resources

`kubectl delete -n argo pod manila-test-pod`  
`kubectl delete -n argo pvc ceph-share-rw-pvc`  
`kubectl delete pv ceph-share-rw-pv`  
`kubectl delete -n ceph-csi-cephfs secret manila-share-secret`  
`kubectl delete configmap -n ceph-csi-cephfs ceph-csi-config`

To test that the PVC mount works

Note that in developing these methods, at the `kubectl describe` step below, we would sometimes get the error \`MountVolume.MountDevice failed for volume "ceph-share-rw-pv" : rpc error: code \= Internal desc \= rpc error: code \= Internal desc \= failed to fetch monitor list using clusterID (12345): missing configuration for cluster ID "12345"\`. Possibly we tried to apply the test pod too soon? We resolved it by deleting all the resources we deployed above, except the configmap, and re-applying them all. It’s possible that was overly heavy-handed and we could have simply deleted and re-applied the test pod.

`kubectl apply -f k8s-setup/manila-test-pod.yaml`

`# # Check pod status`  
`# kubectl get pod -n argo manila-test-pod`  
`kubectl describe pod -n argo manila-test-pod`

`# Once running, exec into the pod`  
`kubectl exec -n argo -it manila-test-pod -- /bin/sh`

`# Inside the pod, check the mount`  
`ls -la /mnt/cephfs`  
`df -h /mnt/cephfs`

`# Test write access`  
`echo "test" > /mnt/cephfs/test-file.txt`  
`cat /mnt/cephfs/test-file.txt`

kubectl delete \-n argo pod manila-test-pod

