import utils
import subprocess

def get_config(path):
  return utils.read_json_file(path)

config_location = "config/conf.json"
community_config_location = "config/community_images.json"
static_config_location = "config/legacy_static_images.json"
config = get_config(config_location)

def main():
  docs = generate_docs()

  utils.write_json_to_file(docs, config["version_master_file"])
  print("copying to remote bucket")
  utils.gsutil_cp(config["version_master_file"], config["doc_bucket"])

def generate_docs():
  docs = []

  #filter for images in the conf that have the generate_docs flag set to true
  image_configs = filter(lambda image: image["automated_flags"]["generate_docs"] == True and image["automated_flags"]["include_in_ui"] == True and image["automated_flags"]["build"] == True, config["image_data"])
  remote_docs = get_current_versions()

  #maps the current documentation to a map of {image_name: version} key values
  remote_versions_list = list(map(lambda image_doc: {image_doc["id"]: image_doc["version"]}, remote_docs))
  remote_versions = utils.flatten_list_of_dicts(remote_versions_list)

  print "current versions detected: " + str(remote_versions)

  legacy_gatk_doc = {}
  legacy_bioconductor_doc = {}

  for image_config in image_configs:
      # Here we check first if the remote documentation exists, then if the local version is the same as the remote. 
      # If the remote documentation exists and the version matches the local, we re-use the old documentation
      remote_doc = list(filter(lambda image_doc: image_doc["id"] == image_config["name"], remote_docs))[0]

      if image_config["name"] in remote_versions and image_config["version"] == remote_versions[image_config["name"]]:
        print "using remote doc: {}".format(remote_doc)
        doc = remote_doc

      else:
        doc = generate_doc_for_image(image_config)

      #Computing legacy  images for gatk and bioconductor
      if image_config["name"] == "terra-jupyter-gatk":
        legacy_gatk_doc = get_legacy_image(image_config["version"], remote_doc)

      if image_config["name"] == "terra-jupyter-bioconductor":
        legacy_bioconductor_doc = get_legacy_image(image_config["version"], remote_doc)
            
      docs.append(doc)

  docs.extend(get_other_docs())
  docs.extend([legacy_gatk_doc, legacy_bioconductor_doc])
  return docs

def get_legacy_image(new_version, remote_doc):
  new_version = new_version.split(".") 
  new_version_patch = int(new_version[2])
  new_version_minor = int(new_version[1])
  new_version_major = int(new_version[0])
  current_version = remote_doc["version"].split(".")
  current_version_patch = int(current_version[2])
  current_version_minor = int(current_version[1])
  current_version_major = int(current_version[0])
  # major version bump
  if new_version_major > current_version_major and (new_version_minor == 0 and new_version_patch == 0):
    return generate_legacy_label(remote_doc)
  # minor version bump
  elif new_version_minor > current_version_minor and (new_version_patch == 0 and current_version_major == new_version_major):
    return generate_legacy_label(remote_doc)
  else: # TODO: remove this code after gatk and bioconductor images have a major or minor version bump
    #if no  major or minor version bump, hardcode legacy  images
    if "terra-jupyter-bioconductor" in remote_doc["image"]:
      return utils.read_json_file(static_config_location)[0]
    else:
      return utils.read_json_file(static_config_location)[1]

def generate_legacy_label(doc):
  if "terra-jupyter-bioconductor" in doc["image"]:
    doc["label"] = "Legacy " + doc["label"]
    return doc
  else:
    doc["label"] = doc["label"].replace("Default", "Legacy GATK")
    return doc

def generate_doc_for_image(image_config):
  version = image_config["version"]
  image_dir = image_config["name"]
  doc = {
    "id": image_dir,
    "label": get_doc_label(image_config),
    "version": version,
    "updated": get_last_updated(image_config),
    "packages": get_doc_link(image_config),
    "image": "{}/{}:{}".format(config['gcr_image_repo'], image_dir, version),
    "requiresSpark": "spark" in image_config["tools"]
  }

  return doc

def get_doc_label(image_config):
  additional_package_names = image_config["packages"]
  tools = image_config["tools"]
  base_label = image_config["base_label"]
  doc_suffix = config["doc_suffix"]

  package_file = "{}-{}-{}".format(image_config['name'], image_config['version'], doc_suffix)
  utils.gsutil_cp(package_file, config["doc_bucket"], copy_to_remote=False)
  packages = utils.read_json_file(package_file)

  additional_package_labels = []
  for tool in additional_package_names.keys():
    labels = map(lambda package: "{} {}".format(package, packages[tool][package]), additional_package_names[tool])
    additional_package_labels = additional_package_labels + list(labels)

  tool_labels = map(lambda tool: "{} {}".format(get_tool_label(tool), packages[tool][tool]), tools)

  labels = list(tool_labels) + list(additional_package_labels)

  label = "{}: ({})".format(base_label,', '.join(labels))

  return label

def get_doc_link(image_config):
  link = "{}/{}/{}-{}-{}".format(config['storage_api'], config['doc_bucket_no_prefix'], image_config["name"], image_config["version"], config['doc_suffix'])
  return link

# will be in YYYY-MM-DD format, which is what terra ui wants
#this function assumes the current version for the image exists in gcr
def get_last_updated(image_config):
  image_repo = config["gcr_image_repo"]
  image_name = image_config["name"]
  version = image_config["version"]
  command = "gcloud container images list-tags {}/{} | grep {} | awk '{{print $NF}}'".format(image_repo, image_name, version)
  ISO8601_date = utils.shell_exec(command)
  terra_date = ISO8601_date.split("T")[0]

  return terra_date

# See definitions in https://docs.google.com/document/d/1qAp1wJTEx1UNtZ4vz1aV4PZRfjyYfF7QkwwOjK4LoD8/edit
def get_other_docs():
  community_docs = utils.read_json_file(community_config_location)

  return community_docs

def get_current_versions():
  try:
    utils.gsutil_cp(config["version_master_file"], config["doc_bucket"], copy_to_remote=False)
    current_versions = utils.read_json_file(config["version_master_file"])
  except subprocess.CalledProcessError:
    print("detected remote file doesn't exist, will regenerate versions")
    current_versions = {}
  except IOError:
    print("detected remote file doesn't exist, will regenerate versions")
    current_versions = {}
  
  return current_versions

def get_tool_label(tool):
  return tool.upper() if tool == 'gatk' else tool.capitalize()

if __name__ == "__main__":
  main()
