import matplotlib.pyplot as plt
import numpy as np

def plot_decision_dashboard(iceberg_start, trajectory, vessel_route, risk_assessment, observed_trajectory=None):
    """
    Generates a professional matplotlib-based representation of the dashboard
    incorporating predicted track, uncertainty, and vessel routes.
    """
    fig, ax = plt.subplots(figsize=(10, 8))
    
    # Plot Vessel Route
    if vessel_route:
        lats = [pt['lat'] for pt in vessel_route]
        lons = [pt['lon'] for pt in vessel_route]
        ax.plot(lons, lats, color='blue', linestyle='--', linewidth=2, label="Vessel Route")
    
    # Plot Iceberg Observation
    ax.scatter([iceberg_start['lon']], [iceberg_start['lat']], color='red', marker='s', s=100, label="Observed Iceberg (Ground Truth)")
    
    # Plot Observed Historical Track (If provided)
    if observed_trajectory:
        obs_lons = [pt['longitude'] for pt in observed_trajectory]
        obs_lats = [pt['latitude'] for pt in observed_trajectory]
        ax.plot(obs_lons, obs_lats, color='black', linewidth=2, label="OBSERVED - Ground Truth")
    
    # Plot Trajectory & Uncertainty
    if trajectory:
        traj_lons = [iceberg_start['lon']] + [pt['longitude'] for pt in trajectory]
        traj_lats = [iceberg_start['lat']] + [pt['latitude'] for pt in trajectory]
        
        # Determine if it's Adjusted or Physics based on warning presence
        is_adjusted = risk_assessment.get("model_version", "").startswith("Adjusted") and "warning" not in risk_assessment
        label = "TRAJECTORY - Forecast" if is_adjusted else "PHYSICS - Baseline Forecast"
        ax.plot(traj_lons, traj_lats, color='orange', linewidth=2, label=label)
        
        # Uncertainty cones (simple circles for matplotlib representation)
        for pt in trajectory:
            radius_deg = pt['uncertainty_radius_km'] / 111.0
            circle = plt.Circle((pt['longitude'], pt['latitude']), radius_deg, color='orange', alpha=0.3)
            ax.add_patch(circle)
        
    ax.set_title(f"Antarctic Navigation Support - Risk: {risk_assessment.get('risk_level', 'UNKNOWN')}")
    ax.set_xlabel("Longitude")
    ax.set_ylabel("Latitude")
    ax.legend()
    ax.grid(True)
    
    # Add Explainable Reason Box
    textstr = f"Risk: {risk_assessment.get('risk_level', 'N/A')}\nAction: {risk_assessment.get('recommendation', 'N/A')}"
    if 'warning' in risk_assessment:
        textstr += f"\nWarning: {risk_assessment['warning']}"
        
    props = dict(boxstyle='round', facecolor='wheat', alpha=0.5)
    ax.text(0.05, 0.95, textstr, transform=ax.transAxes, fontsize=10,
            verticalalignment='top', bbox=props)
            
    # Save the plot
    plt.savefig("decision_dashboard_output.png", dpi=300, bbox_inches="tight")
    print("Dashboard visualization saved to decision_dashboard_output.png")

if __name__ == "__main__":
    raise SystemExit(
        "No mock dashboard data is bundled. Import plot_decision_dashboard() and pass "
        "genuine observed/model outputs from the NAV-X pipeline."
    )
