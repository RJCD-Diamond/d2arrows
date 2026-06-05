# The devcontainer should use the developer target and run as root with podman
# or docker with user namespaces.
FROM ghcr.io/diamondlightsource/ubuntu-devcontainer:noble AS developer

# Add any system dependencies for the developer/build environment here
RUN apt-get update -y && apt-get install -y --no-install-recommends \
    graphviz \
    apt-transport-https \
    ca-certificates \
    curl \
    gnupg \
    unzip \
    && rm -rf /var/lib/apt/lists/*

# Install kubectl from the official Kubernetes repository
RUN mkdir -p -m 755 /etc/apt/keyrings && \
    curl -fsSL https://pkgs.k8s.io/core:/stable:/v1.32/deb/Release.key \
    | gpg --dearmor -o /etc/apt/keyrings/kubernetes-apt-keyring.gpg && \
    chmod 644 /etc/apt/keyrings/kubernetes-apt-keyring.gpg && \
    echo 'deb [signed-by=/etc/apt/keyrings/kubernetes-apt-keyring.gpg] https://pkgs.k8s.io/core:/stable:/v1.32/deb/ /' \
    > /etc/apt/sources.list.d/kubernetes.list && \
    chmod 644 /etc/apt/sources.list.d/kubernetes.list && \
    apt-get update -y && \
    apt-get install -y --no-install-recommends kubectl && \
    rm -rf /var/lib/apt/lists/*

# Install kubelogin (kubectl oidc-login plugin)
RUN ARCH=$(dpkg --print-architecture) && \
    case ${ARCH} in \
    amd64) KUBELOGIN_ARCH=amd64 ;; \
    arm64) KUBELOGIN_ARCH=arm64 ;; \
    *) echo "Unsupported architecture: ${ARCH}" && exit 1 ;; \
    esac && \
    curl -fsSL -o /tmp/kubelogin.zip \
    "https://github.com/int128/kubelogin/releases/latest/download/kubelogin_linux_${KUBELOGIN_ARCH}.zip" && \
    unzip /tmp/kubelogin.zip -d /tmp/kubelogin && \
    install -m 0755 /tmp/kubelogin/kubelogin /usr/local/bin/kubectl-oidc_login && \
    rm -rf /tmp/kubelogin /tmp/kubelogin.zip

# The build stage installs the context into the venv
FROM developer AS build

# Change the working directory to the `app` directory
# and copy in the project
WORKDIR /app
COPY . /app
RUN chmod o+wrX .

# Tell uv sync to install python in a known location so we can copy it out later
ENV UV_PYTHON_INSTALL_DIR=/python

# Sync the project without its dev dependencies
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --locked --no-editable --no-dev --managed-python


# The runtime stage copies the built venv into a runtime container
FROM ubuntu:noble AS runtime

# Runtime dependencies
RUN apt-get update -y && apt-get install -y --no-install-recommends \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Copy kubectl + kubelogin from developer stage
COPY --from=developer /usr/bin/kubectl /usr/bin/kubectl
COPY --from=developer /usr/local/bin/kubectl-oidc_login /usr/local/bin/kubectl-oidc_login

# Copy the python installation from the build stage
COPY --from=build /python /python

# Copy the environment, but not the source code
COPY --from=build /app/.venv /app/.venv
ENV PATH=/app/.venv/bin:$PATH

# change this entrypoint if it is not the same as the repo
ENTRYPOINT ["arrows"]
CMD ["--version"]
