Dragon Nodes Dashboard
======================

**Driverless Control Matrix for TU Brno Racing**

* * *

Overview
--------

When developing the FS driverless architecture, juggling multiple separate terminals to run the IPG CarMaker simulation and various ROS 2 nodes gets incredibly messy. This dashboard completely replaces that chaos. It provides a centralized, IDE-grade graphical interface to orchestrate, introspect, and execute our entire ROS 2 node ecosystem without drowning in terminal windows.

Execution Modes
---------------

Upon launching the application, you must configure the environment connection:

*   **Local Execution:** Spawns and manages processes natively on your current host machine.
*   **Remote Execution (SSH):** Connects directly to the driverless PC (the ass pc) via Tailscale. You must provide the target IP, username, and either a password or the SSH private key path.

Interface Architecture
----------------------

The layout is structured into a three-pane docking workspace designed for rapid operational access:

1.  **Dashboard Grid (Left Panel):** Displays all registered configurations as interactive tiles, categorized into macro blocks (groups).
    *   _Node Cards:_ Click a card to view its telemetry stream. Toggle the Run/Stop button to ignite or kill the specific process. The card will illuminate green when operational.
    *   _Group Cards:_ Utilize the "Run All" or "Stop All" buttons to execute bulk boot or assassination sequences for an entire cluster of nodes simultaneously.
2.  **Contextual Editor (Top Right):** Selecting any node or group transforms this pane into a configuration editor. Here, you can mutate the node's identifier, reassign its group, or rewrite the underlying ROS 2 command. This panel also houses the isolated terminal matrix displaying standard output and error streams for the active selection.
3.  **System Console (Bottom Right):** A read-only diagnostic log tracking fundamental background events, SSH socket states, and network errors. If shit breaks, look here.
