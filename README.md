# Daggerverse Modules for CI/CD Pipeline Management

## 📌 What is this?

This repository contains a set of reusable [Dagger](https://dagger.io) modules that form the foundation of our team's build and release pipeline. The modules help standardize how we build container images, determine deployment environments (latest, stable, review), and calculate build versions using semantic-release.

These modules are designed to be composed and extended — making it easier to maintain consistent and declarative CI/CD logic across multiple projects.

---

## ❓ Why does this exist?

As our teams adopt Dagger for CI/CD, we need a centralized and maintainable way to share logic for:

- Building container images in a consistent way
- Automatically detecting the right environment for a deployment
- Assigning semantic versions based on commit history
- Composing pipelines with reusable, well-tested modules

By organizing these tools into a Daggerverse, we encourage reuse, minimize duplication, and ensure pipeline logic evolves in a predictable, maintainable way.

---

## ⚙️ Modules Overview

### `pipeline-manager` (Main module)
Orchestrates the full pipeline:
- Determines deployment environment (`latest`, `stable`, or `review`)
- Calculates version using `semantic-release`
- Contains the module `chart-updater` that writes the version to the [helm-charts](https://github.com/bcit-ltc/helm-charts) repo
- Contains `helm-oci-chart-releaser` module that packages the helm files into OCI containers and publishes it to github packages

### `build_docker_image`
Handles the container image building logic using configurable inputs (e.g., Dockerfile path, build args).

### `semantic-release`
Wraps `semantic-release` logic to determine the next build version from Git history and commit messages.

### `chart-updater`


### `helm-oci-chart-releaser`


> More modules may be added in the future as our needs evolve.

---

## 📦 Requirements

- [Dagger CLI](https://docs.dagger.io/cli) (v0.9 or later)
- Docker or a container runtime supported by Dagger
- Access to Git repository with semantic versioning
- ...

---

## 🚀 Getting Started

1.
