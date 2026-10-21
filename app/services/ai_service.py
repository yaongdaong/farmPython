from pathlib import Path
from datetime import datetime, timedelta
import numpy as np
from typing import List, Any
from app.config import MODEL_PATH

TORCH_AVAILABLE = True
try:
    import torch
    import torch.nn as nn
except ImportError:
    TORCH_AVAILABLE = False

class WeatherLSTM(nn.Module):
    def __init__(self, input_size=4, hidden_size=64, num_layers=2, output_days=30):
        super(WeatherLSTM, self).__init__()
        self.lstm = nn.LSTM(
            input_size, hidden_size, num_layers, batch_first=True,
            dropout=0.2 if num_layers >1 else 0.0
        )
        self.fc = nn.Sequential(
            nn.Linear(hidden_size, 32),
            nn.ReLU(),
            nn.Linear(32, output_days)
        )
    def forward(self,x):
        out, _ = self.lstm(x)
        out = self.fc(out[:,-1,:])
        return out
    