{ pkgs, ... }: {
  # Which nixpkgs channel to use.
  channel = "stable-24.05"; # or "unstable"
  # Use https://search.nixos.org/packages to find packages
  packages = [
    pkgs.python311
    pkgs.python311Packages.pip
    pkgs.python311Packages.anthropic
    pkgs.python311Packages.fastapi
    pkgs.python311Packages.uvicorn
  ];
  # Sets environment variables in the workspace
  env = {};
  idx = {
    # Search for the extensions you want on https://open-vsx.org/ and use "publisher.id"
    extensions = [
      "ms-python.python"
    ];
    # Enable previews
    previews = {
      enable = true;
      previews = {
        web = {
          command = ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "$PORT"];
          manager = "web";
        };
      };
    };
    # Workspace lifecycle hooks
    workspace = {
      # Runs when a workspace is first created
      onCreate = {
        pip-install = "pip install -r requirements.txt";
      };
      # Runs when the workspace is (re)started
      onStart = {};
    };
  };
}
