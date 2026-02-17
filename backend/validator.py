"""n8n workflow JSON structural validator."""


def validate_workflow(workflow: dict) -> dict:
    """Validate an n8n workflow JSON structure.

    Returns {"valid": bool, "errors": [...], "warnings": [...]}
    """
    errors = []
    warnings = []

    # 1. Nodes array exists and is non-empty
    nodes = workflow.get("nodes")
    if not isinstance(nodes, list):
        errors.append("Missing or invalid 'nodes' array")
        return {"valid": False, "errors": errors, "warnings": warnings}
    if len(nodes) == 0:
        errors.append("'nodes' array is empty — workflow must have at least one node")
        return {"valid": False, "errors": errors, "warnings": warnings}

    # 2. Connections object exists
    connections = workflow.get("connections")
    if not isinstance(connections, dict):
        errors.append("Missing or invalid 'connections' object")

    # 3. First node should be a trigger
    first_node = nodes[0]
    first_type = first_node.get("type", "").lower()
    if "trigger" not in first_type and "webhook" not in first_type:
        warnings.append(
            f"First node '{first_node.get('name', '?')}' (type: {first_node.get('type', '?')}) "
            f"does not appear to be a trigger node"
        )

    # 4. All nodes have required fields
    required_fields = ["name", "type", "parameters", "position", "typeVersion"]
    node_names = set()
    for i, node in enumerate(nodes):
        for field in required_fields:
            if field not in node:
                errors.append(f"Node {i} ('{node.get('name', '?')}') missing required field '{field}'")

        # 5. No duplicate node names
        name = node.get("name")
        if name:
            if name in node_names:
                errors.append(f"Duplicate node name: '{name}'")
            node_names.add(name)

        # 8. Position values are valid
        pos = node.get("position")
        if pos is not None:
            if not isinstance(pos, (list, tuple)) or len(pos) != 2:
                errors.append(f"Node '{name}': position must be a 2-element array, got {pos}")
            elif not all(isinstance(v, (int, float)) for v in pos):
                errors.append(f"Node '{name}': position values must be numbers, got {pos}")

    # 6 & 7. Validate connections
    if isinstance(connections, dict):
        for source_name, outputs in connections.items():
            if source_name not in node_names:
                errors.append(f"Connection references non-existent source node: '{source_name}'")
            if not isinstance(outputs, dict):
                continue
            for output_key, targets_list in outputs.items():
                if not isinstance(targets_list, list):
                    continue
                for target_group in targets_list:
                    if not isinstance(target_group, list):
                        continue
                    for conn in target_group:
                        target_name = conn.get("node")
                        if target_name and target_name not in node_names:
                            errors.append(
                                f"Connection from '{source_name}' references "
                                f"non-existent target node: '{target_name}'"
                            )

    return {
        "valid": len(errors) == 0,
        "errors": errors,
        "warnings": warnings,
    }
