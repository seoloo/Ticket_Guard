from django.test import SimpleTestCase, override_settings
from django.urls import reverse


@override_settings(EVENT_PUBLISHER='mock')
class BoardPageTests(SimpleTestCase):
    def test_public_pages_and_active_sidebar(self):
        for name, title in [('notices', '공지사항'), ('free_board', '자유게시판')]:
            with self.subTest(name=name):
                response = self.client.get(reverse(name))
                self.assertEqual(response.status_code, 200)
                self.assertTemplateUsed(response, 'boards/list.html')
                self.assertContains(response, f'<h1 id="board-title">{title}</h1>')
                self.assertContains(response, f'href="{reverse(name)}" aria-current="page"')
                self.assertContains(response, '/static/boards.css')
                self.assertNotContains(response, '<nav aria-label="주 메뉴">')
                self.assertIn('no-store', response['Cache-Control'])

    def test_home_menu_points_to_separate_pages(self):
        response = self.client.get('/')
        self.assertContains(response, 'href="/notices/">공지사항</a>')
        self.assertContains(response, 'href="/free-board/">자유게시판</a>')

    def test_free_board_author_column_and_empty_state(self):
        response = self.client.get(reverse('free_board'))
        self.assertContains(response, '<th scope="col">작성자</th>')
        self.assertContains(response, 'colspan="5"')
        self.assertContains(response, '등록된 게시글이 없습니다.')
        self.assertNotContains(self.client.get(reverse('notices')), '<th scope="col">작성자</th>')

    def test_query_is_escaped_bounded_and_category_validated(self):
        response = self.client.get(reverse('notices'), {'q': '<script>alert(1)</script>', 'category': 'unknown'})
        self.assertContains(response, '&lt;script&gt;alert(1)&lt;/script&gt;')
        self.assertNotContains(response, '<script>alert(1)</script>')
        self.assertEqual(response.context['category'], '전체')
        self.assertContains(response, '검색 결과가 없습니다.')
        response = self.client.get(reverse('notices'), {'q': 'x' * 200})
        self.assertEqual(len(response.context['query']), 100)

    def test_pages_preserve_signed_in_account_and_reject_posts(self):
        session = self.client.session
        session['user'] = 'ticketguard'
        session.save()
        self.client.cookies['sessionid'] = session.session_key
        response = self.client.get(reverse('notices'))
        self.assertContains(response, 'ticketguard 님')
        self.assertContains(response, 'id="logout"')
        self.assertEqual(self.client.post(reverse('notices')).status_code, 405)
