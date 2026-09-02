# This is a stub which will need to be implemented in the future. The goal of this script is to pull
# the parsed metadata from S3. This data will have a sensor-specific schema and the goal of this
# script is to standardize this data so it fits one cross-sensor schema. Additionally, this script
# should compute derived fields summarizing the whole collect of data.

# Convert to the standardized OFO data format
# * This will depend on knowing the sensor model
# * TODO it's possible in this case that we could parse the sensor model automatically

# TODO should this data be re-uploaded somewhere?
# * Likely the same place, with a different name
