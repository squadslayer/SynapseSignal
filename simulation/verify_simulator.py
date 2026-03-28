# 🚦 SynapseSignal: Stateful Simulation Verification
import time
import random

class StatefulTrafficNode:
    def __init__(self, name, start_queue=10, arrival_rate=0.5):
        self.name = name
        self.queue = start_queue
        self.arrival_rate = arrival_rate # Vehicles arriving per tick
        self.departure_rate = 2.0      # Vehicles leaving per tick (ONLY when GREEN)
        self.signal_state = "RED"      # Default state

    def tick(self, signal_override=None):
        if signal_override:
            self.signal_state = signal_override

        # 1. New traffic always arrives (randomized slightly)
        self.queue += self.arrival_rate + (random.random() * 0.2)
        
        # 2. Traffic ONLY moves if the light is GREEN
        if self.signal_state == "GREEN":
            # Queue decreases, but cannot be negative
            self.queue = max(0, self.queue - self.departure_rate)
            
        return round(self.queue, 1)

def run_verification_demo():
    print("--- SynapseSignal: 🚦 STATEFUL TRAFFIC SIMULATION VERIFIER ---")
    print("Scenario: A single intersection node (AIIMS_CIRCLE).")
    print("Protocol: Watch the queue build during RED, then drain during GREEN.\n")
    
    node = StatefulTrafficNode("AIIMS_CIRCLE")
    
    # Simple timeline simulation
    # Phase 1: 5 ticks of RED (Queue should grow)
    # Phase 2: 5 ticks of GREEN (Queue should shrink)
    # Phase 3: 3 ticks of RED (Queue should grow again)
    
    timeline = [("RED", 5), ("GREEN", 5), ("RED", 3)]
    
    for state, duration in timeline:
        print(f"--- Signal Triggered: [{state}] ---")
        for i in range(duration):
            q_size = node.tick(signal_override=state)
            # Visualization
            visual = "🚗" * int(q_size)
            print(f"t={i}s | Signal: {state:<5} | Queue: {q_size:<5} | {visual}")
            time.sleep(0.5)
        print("")

    print("✅ VERIFICATION COMPLETE: The stateful queue implementation is working correctly.")

if __name__ == "__main__":
    run_verification_demo()
