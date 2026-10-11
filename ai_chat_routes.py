"""ai_chat_routes.py - Authenticated Admin Routes for AI Cricket Assistant.

Provides dedicated web views and JSON API endpoints for the AI Chat interface.
All endpoints are strictly guarded by @admin_required.
"""

from flask import Blueprint, render_template, request, jsonify, session
import ai_chat_storage
import ai_service

ai_chat_bp = Blueprint('ai_chat', __name__)


def register_ai_chat_routes(admin_bp, admin_required):
    """Registers all AI chat endpoints under the existing admin blueprint."""

    @admin_bp.route('/ai-chat', methods=['GET'])
    @admin_required
    def ai_chat_view():
        """Renders the dedicated AI Cricket Assistant chat page."""
        admin_username = session.get('admin_user', 'admin')
        # Load active conversations for sidebar
        conversations = ai_chat_storage.list_conversations(admin_username)
        is_configured = ai_service.is_groq_configured()
        model_name = ai_service.get_current_model()

        return render_template(
            'admin/ai_chat.html',
            conversations=conversations,
            is_configured=is_configured,
            model_name=model_name,
            admin_user=admin_username
        )

    @admin_bp.route('/api/ai/chat', methods=['POST'])
    @admin_required
    def api_ai_chat():
        """Receives a user message, calls Groq with dynamic data retrieval, and returns the AI response."""
        try:
            data = request.get_json(silent=True) or {}
            raw_msg = data.get('message')
            user_message = str(raw_msg).strip() if raw_msg is not None else ''
            
            raw_conv = data.get('conversation_id')
            conversation_id = str(raw_conv).strip() if raw_conv is not None and str(raw_conv).strip() else None

            if not user_message:
                return jsonify({'success': False, 'error': 'Message content cannot be empty.'}), 400

            admin_username = session.get('admin_user', 'admin')

            # Process message via Groq AI service
            result = ai_service.process_chat_message(
                admin_username=admin_username,
                user_message=user_message,
                conversation_id=conversation_id
            )

            return jsonify(result)
        except Exception as e:
            return jsonify({
                'success': False,
                'error': f"Internal server error: {str(e)}"
            }), 500

    @admin_bp.route('/api/ai/conversations', methods=['GET'])
    @admin_required
    def api_ai_conversations():
        """Lists active (non-expired) conversations for the logged-in administrator."""
        admin_username = session.get('admin_user', 'admin')
        conversations = ai_chat_storage.list_conversations(admin_username)
        return jsonify({
            'success': True,
            'conversations': conversations
        })

    @admin_bp.route('/api/ai/history/<conversation_id>', methods=['GET'])
    @admin_required
    def api_ai_history(conversation_id):
        """Retrieves message history for a specific active conversation."""
        admin_username = session.get('admin_user', 'admin')
        conv = ai_chat_storage.get_conversation(conversation_id, admin_username=admin_username)
        
        if not conv:
            return jsonify({'success': False, 'error': 'Conversation not found or expired.'}), 404

        messages = ai_chat_storage.get_messages(conversation_id)
        # Filter messages for UI display (user and assistant only; tool calls are in metadata)
        displayable = []
        for m in messages:
            if m.get('role') in ('user', 'assistant'):
                displayable.append({
                    'id': m.get('id'),
                    'role': m.get('role'),
                    'content': m.get('content', ''),
                    'metadata': m.get('metadata'),
                    'created_at': m.get('created_at')
                })

        return jsonify({
            'success': True,
            'conversation': conv,
            'messages': displayable
        })

    @admin_bp.route('/api/ai/history/<conversation_id>', methods=['DELETE'])
    @admin_required
    def api_ai_delete_conversation(conversation_id):
        """Deletes a specific AI conversation."""
        admin_username = session.get('admin_user', 'admin')
        deleted = ai_chat_storage.delete_conversation(conversation_id, admin_username=admin_username)
        return jsonify({'success': deleted})

    @admin_bp.route('/api/ai/clear', methods=['POST'])
    @admin_required
    def api_ai_clear_all():
        """Clears all AI chat conversations for the logged-in administrator."""
        admin_username = session.get('admin_user', 'admin')
        ai_chat_storage.clear_admin_conversations(admin_username)
        return jsonify({'success': True, 'message': 'All AI chat conversations cleared.'})

    @admin_bp.route('/api/ai/status', methods=['GET'])
    @admin_required
    def api_ai_status():
        """Returns the current Groq AI integration status."""
        return jsonify({
            'is_configured': ai_service.is_groq_configured(),
            'model': ai_service.get_current_model()
        })
