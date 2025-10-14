## Admin guide: Creating a K8s cluster with Magnum

This guide is for the ADMIN person (currently Derek). We only need one cluster so this guide is not necessary for the whole team. There is a separate guide on cluster management that is for the whole team. 

Key resource used in creating this guide: [https://gitlab.com/jetstream-cloud/jetstream2/eot/tutorials/magnum-tutorial/-/wikis/beginners\_guide\_to\_magnum\_on\_JS2](https://gitlab.com/jetstream-cloud/jetstream2/eot/tutorials/magnum-tutorial/-/wikis/beginners_guide_to_magnum_on_JS2)

## One-time local machine software setup

These instructions will set up your local (Linux, Mac, or WSL) machine to control the cluster through the command line.

Make sure you have a recent python interpreter and the python venv utility, and create a python virtual environment for OpenStack management:

`sudo apt update`   
`sudo apt install -y python3-full python3-venv`  
`python3 -m venv ~/venv/openstack`

Activate that environment, and within it, install the relevant OpenStack command line tools.

`# Activate env`  
`source ~/venv/openstack/bin/activate`

`# OpenStack utils`  
`pip install -U python-openstackclient python-magnumclient python-designateclient` 

Install the Kubernetes control utility kubectl (kubectl steps from [here](https://kubernetes.io/docs/tasks/tools/install-kubectl-linux/)):

`# Kubectl`  
`sudo apt install -y apt-transport-https ca-certificates curl gnupg`   
`curl -fsSL https://pkgs.k8s.io/core:/stable:/v1.33/deb/Release.key | sudo gpg --dearmor -o /etc/apt/keyrings/kubernetes-apt-keyring.gpg`  
`sudo chmod 644 /etc/apt/keyrings/kubernetes-apt-keyring.gpg`  
`echo 'deb [signed-by=/etc/apt/keyrings/kubernetes-apt-keyring.gpg] https://pkgs.k8s.io/core:/stable:/v1.33/deb/ /' | sudo tee /etc/apt/sources.list.d/kubernetes.list`  
`sudo chmod 644 /etc/apt/sources.list.d/kubernetes.list`  
`sudo apt update`  
`sudo apt install -y kubectl`

Create an application credential. In Horizon, go to Identity, Application Credentials. Click Create. Do not change the roles, do not set a secret (one will be generated), but do set an expiration date and do check “unrestricted”. It needs to be unrestricted because this credential needs to allow for the creation of more app creds (for the cluster), as that is what Magnum does. Download the openrc file and put it in the OFO [Valutwarden](http://vault.focal-lab.org) organization where OFO members can access it.

Copy the application credential onto your *local computer* (do not put it on a JS2 machine), ideally into `~/.ofocluster/app-cred-ofocluster-openrc.sh`.

Source the application credential (which sets relevant env vars for the OpenStack command line tools to use).

`source ~/.ofocluster/app-cred-ofocluster-openrc.sh`

Create a (dummy) OpenStack keypair. If you wanted, you could save the private key that is created (displayed when you run this) locally in order to SSH into the cluster nodes later. But they won’t even have public IP addresses so this is more just to satisfy Magnum because it requires it for cluster creation.

`openstack keypair create my-openstack-keypair-name` 

OR, you could specify an existing key you normally use.

`openstack keypair create my-openstack-keypair-name --public-key ~/.ssh/id_rsa.pub`

Enable shell completion for OpenStack and Kubectl

*`# Create a directory for completion scripts`*  
`mkdir -p ~/.bash_completion.d`

*`# Generate completion scripts`*  
`openstack complete > ~/.ofocluster/openstack-completion.bash`  
`kubectl completion bash > ~/.ofocluster/kubectl-completion.bash`

*`# Add to ~/.bashrc`*  
`echo 'source ~/.ofocluster/openstack-completion.bash' >> ~/.bashrc`  
`echo 'source ~/.ofocluster/kubectl-completion.bash' >> ~/.bashrc`

## Cluster creation

Assuming you’re in a fresh shell session where you have not done this yet, enter your js2 venv and source the application credential (which sets relevant env vars for the OpenStack command line tools to use).

`source ~/venv/openstack/bin/activate`  
`source ~/.ofocluster/app-cred-ofocluster-openrc.sh`

See available cluster templates

`openstack coe cluster template list` 

Specify the parameters of the deployment as locally scoped env vars and then deploy. Probably choose the most recent K8s version (highest number in the template list). It seems to work fine for the master node to be a m3.small. We’ll deploy a cluster with a single worker node that is also m3.small, because when we want to scale up the cluster, we’ll add nodegroups. This initial spec is just the base setup for when we’re not running anything on it.

| TEMPLATE\="kubernetes-1-33-jammy"FLAVOR\="m3.small"MASTER\_FLAVOR\="m3.small"BOOT\_VOLUME\_SIZE\_GB\=80\# Number of instancesN\_MASTER\=1 \# Needs to be oddN\_WORKER\=1\# Min and max number of worker nodes (if using autoscaling)AUTOSCALE\=falseN\_WORKER\_MIN\=1N\_WORKER\_MAX\=5NETWORK\_ID\=$(openstack network show \--format value \-c id auto\_allocated\_network)SUBNET\_ID\=$(openstack subnet show \--format value \-c id auto\_allocated\_subnet\_v4)KEYPAIR\=my-openstack-keypair-name\# Deploy\!openstack coe cluster create \--cluster-template $TEMPLATE \\    \--master-count $N\_MASTER \--node-count $N\_WORKER \\    \--master-flavor $MASTER\_FLAVOR \--flavor $FLAVOR \\    \--merge-labels \\    \--labels auto\_scaling\_enabled\=$AUTOSCALE \\    \--labels min\_node\_count\=$N\_WORKER\_MIN \\    \--labels max\_node\_count\=$N\_WORKER\_MAX \\    \--labels boot\_volume\_size\=$BOOT\_VOLUME\_SIZE\_GB \\    \--keypair $KEYPAIR \\    \--fixed-network "${NETWORK\_ID}" \\    \--fixed-subnet "${SUBNET\_ID}" \\    "ofocluster" |
| :---- |

Check status

| openstack coe cluster list openstack coe cluster show ofocluster openstack coe nodegroup list ofocluster |
| :---- |

Or with formatting that makes it easier to copy the cluster UUID if you need to:

| openstack coe cluster list \--format value \-c uuid \-c name |
| :---- |

## Set up kubectl to control Kubernetes on the cluster

This is required once the first time you interact with Kubernetes on the cluster. `kubectl` is a tool to control Kubernetes–which is the cluster’s software, not its nodes–from your local command line.

Once the `openstack coe cluster list` status changes to CREATE\_COMPLETE, get the Kubernetes configuration file kubeconfig (saves it to the KUBECONFIG env var), save the file's absolute path location to a variable and rename to a more descriptive name:

| openstack coe cluster config "ofocluster" \--force chmod 600 config mkdir \-p \~/.ofocluster mv \-i config \~/.ofocluster/ofocluster.kubeconfig export KUBECONFIG=\~/.ofocluster/ofocluster.kubeconfig |
| :---- |

## Kubernetes management

If you are resuming cluster management from this point after a reboot, you will need to re-set the KUBECONFIG env var and source the application credential:

| source \~/venv/openstack/bin/activate export KUBECONFIG\=\~/.ofocluster/ofocluster.kubeconfig `source ~/.ofocluster/app-cred-ofocluster-openrc.sh` |
| :---- |

We should be able to use kubectl commands now. Let's see our recently created cluster nodes:

| kubectl get nodes |
| :---- |

We can run commands on a node with:

| \# Start a debug session on a specific nodekubectl debug node/\<node-name\> \-it \--image=ubuntu\# Once inside, you have host access via /host\# Check kernel moduleschroot /host modprobe ceph chroot /host lsmod | grep ceph |
| :---- |

Or run a one-off command **to check disk usage**:

| kubectl debug node/\<node-name\> \-it \--image=busybox \-- df \-h |
| :---- |

…and look for the /dev/vda1 volume. Then delete the debugging pods:

| kubectl get pods \-o name | grep node\-debugger | xargs kubectl delete |
| :---- |

## 

## 

## Cluster resizing

These are instructions for managing which nodes are in the cluster, not what software is running on them.

Resize the cluster by adding or removing nodes (the original worker group, not a later-added nodegroup). We will likely not do this, relying instead on nodegroups for specific runs.

| openstack coe cluster resize "ofocluster" 4 |
| :---- |

To add a new nodegroup, first specify its parameters (e.g. instance flavor) and then use OpenStack to create it.

| NODEGROUP\_NAME\=cpu-group  \#gpu-groupFLAVOR\=m3.quad  \#"g3.medium"N\_WORKER\=1AUTOSCALE\=falseN\_WORKER\_MIN\=1N\_WORKER\_MAX\=5DOCKER\_VOLUME\_SIZE\_GB\=80\#BOOT\_VOLUME\_SIZE\_GB\=50openstack coe nodegroup create ofocluster $NODEGROUP\_NAME \\    \--flavor $FLAVOR \\    \--node-count $N\_WORKER \\    \--labels auto\_scaling\_enabled\=$AUTOSCALE \\    \--labels min\_node\_count\=$N\_WORKER\_MIN \\    \--labels max\_node\_count\=$N\_WORKER\_MAX \\    \--labels boot\_volume\_size\=$BOOT\_VOLUME\_SIZE\_GB |
| :---- |

The next set of instructions allow you to increase or decrease the number of nodes in a nodegroup.  When decreasing the number of nodes, it is best practice to drain the Kubernetes pods from them first.  When reducing the size, we don't know which nodes openstack will delete, so we have to drain the whole node group. That's the same thing we'd want to do if we're deleting a node group.  Use this command to do that.

NODEGROUP\_NAME\=cpu-group  
kubectl get nodes \-l capi.stackhpc.com/node-group\=$NODEGROUP\_NAME \-o name | xargs \-I {} kubectl drain {} \--ignore-daemonsets \--delete-emptydir-data

Resize a nodegroup (change the number of nodes)

| N\_WORKER\=2 NODEGROUP\_NAME=cpu-group openstack coe cluster resize ofocluster \--nodegroup $NODEGROUP\_NAME $N\_WORKER |
| :---- |

Delete a nodegroup

| openstack coe nodegroup delete ofocluster $NODEGROUP\_NAME |
| :---- |

Delete the cluster:

| openstack coe cluster delete "ofocluster"  |
| :---- |

## Graphana dashboard

\# Port-forward Grafana to your local machine  
kubectl port-forward \-n monitoring-system svc/kube-prometheus-stack-grafana 3000:80  
http://localhost:3000

## K8s dashboard

kubectl create serviceaccount dashboard-admin \-n kubernetes-dashboard

kubectl create clusterrolebinding dashboard-admin \\  
  \--clusterrole=cluster-admin \\  
  \--serviceaccount=kubernetes-dashboard:dashboard-admin

kubectl create token dashboard-admin \-n kubernetes-dashboard \--duration=24h

\# Port-forward (if not already running)  
kubectl port-forward \-n kubernetes-dashboard svc/kubernetes-dashboard 8443:443

https://localhost:8443