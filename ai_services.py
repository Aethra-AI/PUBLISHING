# -*- coding: utf-8 -*-
import os
from openai import OpenAI
from dotenv import load_dotenv

class AIService:
    def __init__(self):
        load_dotenv()
        api_key = os.getenv("OPENAI_API_KEY")
        if not api_key:
            raise ValueError("No se encontró la OPENAI_API_KEY en el archivo .env")
        self.client = OpenAI(api_key=api_key)

    def generate_tags_for_text(self, text_content):
        """
        Analiza un texto y devuelve una lista de etiquetas relevantes.
        """
        if not text_content:
            return []
        try:
            prompt = f"""
            Eres un experto en marketing digital. Analiza el siguiente texto de una publicación y extrae de 3 a 5 palabras clave o etiquetas relevantes para categorizarlo.
            Responde únicamente con las etiquetas separadas por comas, en minúsculas y sin espacios extra.
            Ejemplo de respuesta: oferta,venta de coches,segunda mano,ford focus
            
            TEXTO A ANALIZAR:
            '{text_content}'
            """
            
            completion = self.client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[{"role": "user", "content": prompt}],
                temperature=0.2,
            )
            
            raw_tags = completion.choices[0].message.content
            # Limpiar la respuesta para asegurar el formato
            tags = [tag.strip() for tag in raw_tags.split(',') if tag.strip()]
            return tags
            
        except Exception as e:
            print(f"Error al generar etiquetas con IA: {e}")
            return []
    
    def generate_text_variations(self, topic, count=5):
        """
        Genera variaciones de texto sobre un tema específico.
        """
        try:
            prompt = (f"Eres un experto en marketing para Facebook. Genera {count} variaciones de texto cortas, creativas y atractivas sobre el siguiente tema: '{topic}'.\n"
                        "INSTRUCCIONES ESTRICTAS:\n"
                        "1. No uses numeración ni viñetas.\n"
                        "2. Separa CADA variación con el separador especial '###'.\n"
                        "3. El tono debe ser natural, conversacional y que invite a la acción.")
            
            completion = self.client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[{"role": "user", "content": prompt}],
                temperature=0.7,
            )
            raw_text = completion.choices[0].message.content
            new_texts = [txt.strip() for txt in raw_text.split('###') if txt.strip()]
            return new_texts
        except Exception as e:
            print(f"Error al generar textos con IA: {e}")
            return []

# Instancia global
ai_service = AIService()