import os
import sys
import torch
import torch.nn as nn
import numpy as np
from flask import Flask, request, jsonify, render_template
from flask_cors import CORS
import logging

# Set up logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Initialize Flask app
app = Flask(__name__, template_folder='templates', static_folder='static')
CORS(app)

# Device configuration (use cuda:0 or fallback to cpu)
device = torch.device('cuda' if torch.cuda.is_available() else 'cpu')
logger.info(f"Using device: {device}")

# Define model dimensions
hidden_dim = 128

# Import CrossPPI modules
sys.path.append(os.path.dirname(os.path.abspath(__file__)))
from model import Protein_feature_extraction, cross_attention
from data.protein_processor import ProteinInference

# PPI model definition matching main_cv.py / t.py
class PPI(nn.Module):
    def __init__(self):
        super(PPI, self).__init__()
        self.ligand_graph_model = Protein_feature_extraction(hidden_dim)
        self.receptor_graph_model = Protein_feature_extraction(hidden_dim)
        self.cross_attention = cross_attention(hidden_dim)
        
        self.line1 = nn.Linear(hidden_dim * 2, 1024)
        self.line2 = nn.Linear(1024, 512)
        self.line3 = nn.Linear(512, 1)
        self.dropout = nn.Dropout(0.2)
        
        self.ligand1 = nn.Linear(hidden_dim, hidden_dim * 4)
        self.receptor1 = nn.Linear(hidden_dim, hidden_dim * 4)
        
        self.ligand2 = nn.Linear(hidden_dim * 4, hidden_dim)
        self.receptor2 = nn.Linear(hidden_dim * 4, hidden_dim)
        
        self.relu = nn.ReLU()
    
    def forward(self, ligand_batch, receptor_batch):
        ligand_out_seq, ligand_out_graph, ligand_mask_seq, ligand_mask_graph, ligand_seq_final, ligand_graph_final = self.ligand_graph_model(ligand_batch, device)
        receptor_out_seq, receptor_out_graph, receptor_mask_seq, receptor_mask_graph, receptor_seq_final, receptor_graph_final = self.receptor_graph_model(receptor_batch, device)
        
        context_layer, attention_score = self.cross_attention(
            [ligand_out_seq, ligand_out_graph, receptor_out_seq, receptor_out_graph],
            [ligand_mask_seq, ligand_mask_graph, receptor_mask_seq, receptor_mask_graph],
            device
        )

        out_ligand = context_layer[-1][0]
        out_receptor = context_layer[-1][1]
        
        ligand_mask_combined = torch.cat((ligand_mask_seq, ligand_mask_graph), dim=1)
        receptor_mask_combined = torch.cat((receptor_mask_seq, receptor_mask_graph), dim=1)
        
        ligand_cross_seq = ((out_ligand * ligand_mask_combined.unsqueeze(dim=2)).mean(dim=1) + ligand_seq_final) / 2
        ligand_cross_stru = ((out_ligand * ligand_mask_combined.unsqueeze(dim=2)).mean(dim=1) + ligand_graph_final) / 2        

        ligand_cross = (ligand_cross_seq + ligand_cross_stru) / 2
        ligand_cross = self.ligand2(self.dropout(self.relu(self.ligand1(ligand_cross))))

        receptor_cross_seq = ((out_receptor * receptor_mask_combined.unsqueeze(dim=2)).mean(dim=1) + receptor_seq_final) / 2
        receptor_cross_stru = ((out_receptor * receptor_mask_combined.unsqueeze(dim=2)).mean(dim=1) + receptor_graph_final) / 2
        
        receptor_cross = (receptor_cross_seq + receptor_cross_stru) / 2
        receptor_cross = self.receptor2(self.dropout(self.relu(self.receptor1(receptor_cross))))   
        
        out = torch.cat((ligand_cross, receptor_cross), 1)
        out = self.line1(out)
        out = self.dropout(self.relu(out))
        out = self.line2(out)
        out = self.dropout(self.relu(out))
        out = self.line3(out)
        
        return out

# Global models dictionary
models = {}

def load_models():
    """Load the 5 ensemble model folds."""
    logger.info("Loading ensemble models into memory...")
    save_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "save")
    for fold in range(1, 6):
        model_name = f"model_cv_(t300(5_fold))2_{fold}_1.pth"
        model_path = os.path.join(save_dir, model_name)
        if not os.path.exists(model_path):
            logger.error(f"Model file not found: {model_path}")
            continue
        try:
            model = PPI().to(device)
            model.load_state_dict(torch.load(model_path, map_location=device))
            model.eval()
            models[fold] = model
            logger.info(f"Successfully loaded model fold {fold}")
        except Exception as e:
            logger.error(f"Error loading model fold {fold}: {str(e)}")

# Load models at module import
load_models()

@app.route('/')
def home():
    """Serve the single-page application frontend."""
    return render_template('index.html')

@app.route('/api/predict', methods=['POST'])
def predict():
    """Run prediction on ligand and receptor sequences."""
    try:
        data = request.json or {}
        ligand_seq = data.get('ligand', '').strip().upper()
        receptor_seq = data.get('receptor', '').strip().upper()

        if not ligand_seq or not receptor_seq:
            return jsonify({'success': False, 'error': 'Both ligand and receptor sequences are required.'}), 400

        # Simple validation for amino acid characters
        valid_chars = set("ACDEFGHIKLMNPQRSTVWYX")
        if not all(char in valid_chars for char in ligand_seq) or not all(char in valid_chars for char in receptor_seq):
            return jsonify({'success': False, 'error': 'Invalid amino acid sequence. Use standard IUPAC single-letter codes.'}), 400

        if len(models) < 5:
            return jsonify({'success': False, 'error': 'Ensemble models not fully loaded. Please check server logs.'}), 500

        logger.info(f"Received prediction request. Ligand len: {len(ligand_seq)}, Receptor len: {len(receptor_seq)}")

        # Process sequences (extract features & generate ESM embeddings)
        process_ligand = ProteinInference(sequence=ligand_seq)
        processed_ligand = process_ligand.process()
        
        process_receptor = ProteinInference(sequence=receptor_seq)
        processed_receptor = process_receptor.process()

        # Run inference across all 5 folds
        preds = []
        with torch.no_grad():
            l_batch = processed_ligand.to(device)
            r_batch = processed_receptor.to(device)
            for fold in range(1, 6):
                pred = models[fold](l_batch, r_batch).item()
                preds.append(pred)

        mean_pKd = float(np.mean(preds))
        std_pKd = float(np.std(preds))
        
        # Confidence score derived from ensemble disagreement: exp(-std)
        confidence = float(np.exp(-std_pKd))

        response = {
            'success': True,
            'pKd': round(mean_pKd, 2),
            'confidence': round(confidence, 2),
            'std': round(std_pKd, 3),
            'predictions': [round(p, 3) for p in preds],
            'ligand_len': len(ligand_seq),
            'receptor_len': len(receptor_seq)
        }
        
        logger.info(f"Prediction complete. pKd: {response['pKd']}, Confidence: {response['confidence']}")
        return jsonify(response)

    except Exception as e:
        logger.error(f"Error in prediction handler: {str(e)}", exc_info=True)
        return jsonify({'success': False, 'error': f"Prediction failed: {str(e)}"}), 500

if __name__ == '__main__':
    # Use PORT env var for cloud deployment (Render, Railway, etc.), default to 5000 locally
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=False)
